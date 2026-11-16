"""Help requests and guest links."""

from datetime import timedelta

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    GuestLinkLimitError,
    InvalidTransitionError,
    SelfClaimError,
)
from app.modules.admission.domain.help_proofs import HelperActivity, MetricView
from app.modules.admission.domain.workflow import HelpRequest
from app.shared.ids import new_id
from tests.admission.unit.help_kit import HELPER, STUDENT, HelpKit

import pytest


async def _assigned(k: HelpKit) -> tuple[AdmissionContext, HelpRequest]:
    k.h.directory[HELPER] = "Mentor M"
    ctx = await k.ctx()
    req = await k.help.create(ctx, "website", "review my site", item_id=k.item)
    await k.help.assign(ctx, req.id, HELPER)
    return ctx, req


async def test_full_help_flow_and_notifications() -> None:
    k = HelpKit()
    ctx, req = await _assigned(k)
    helper = await k.helper_ctx()
    await k.help.accept(helper, req.id)
    await k.help.respond(helper, req.id, "looks good")
    await k.help.deliver(helper, req.id)
    done = await k.help.close(ctx, req.id)
    assert done.status == "closed"
    assert len(k.h.notifications) >= 2
    detail = await k.help.get(ctx, req.id)
    assert [r.text for r in detail.responses] == ["looks good"]


async def test_wrong_helper_and_bad_transition() -> None:
    k = HelpKit()
    ctx, req = await _assigned(k)
    with pytest.raises(AdmissionNotFoundError):
        await k.help.accept(await k.ctx(), req.id)  # the owner is not the helper
    helper = await k.helper_ctx()
    with pytest.raises(InvalidTransitionError):
        await k.help.deliver(helper, req.id)  # not accepted yet


async def test_self_claim_refused() -> None:
    k = HelpKit()
    ctx = await k.ctx()
    k.h.directory[STUDENT] = "Me"
    req = await k.help.create(ctx, "other", "help")
    with pytest.raises((SelfClaimError, AdmissionNotFoundError)):
        await k.help.assign(ctx, req.id, STUDENT)


async def test_helper_sees_reduced_activities_only() -> None:
    k = HelpKit()
    k.h.activities = [
        HelperActivity(
            "Captain", "Club", "Led it", "club", (MetricView("n", "3", None),)
        )
    ]
    _, req = await _assigned(k)
    detail = await k.help.get(await k.helper_ctx(), req.id)
    assert detail.as_helper and detail.activities is not None
    fields = set(HelperActivity.__dataclass_fields__)
    assert fields == {"position", "org", "description", "kind", "current_metrics"}


async def test_guest_lifecycle_and_uniform_404() -> None:
    k = HelpKit()
    ctx = await k.ctx()
    made = await k.guest.create(ctx, label="Coach", brief="look")
    assert made.token.startswith("gst_")
    assert made.token not in {r.link.token_hash for r in k.h.links.values()}
    sess = await k.guest.redeem(made.token, "1.2.3.4")
    view = await k.guest.view(sess.token, "1.2.3.4")
    assert view.brief == "look"
    resp = await k.guest.respond(sess.token, "1.2.3.4", "advice", None)
    assert resp.guest_link_id is not None
    rotated = await k.guest.rotate(ctx, made.record.link.id)
    with pytest.raises(AdmissionNotFoundError):
        await k.guest.redeem(made.token, None)  # revoked by rotation
    await k.guest.redeem(rotated.token, None)
    with pytest.raises(AdmissionNotFoundError):
        await k.guest.redeem("gst_unknown", None)  # same error as revoked


async def test_guest_expiry_session_cap_and_active_limit() -> None:
    k = HelpKit(max_active=1)
    ctx = await k.ctx()
    made = await k.guest.create(ctx, label=None)
    with pytest.raises(GuestLinkLimitError):
        await k.guest.create(ctx, label=None)
    await k.guest.redeem(made.token, None)
    await k.guest.redeem(made.token, None)
    with pytest.raises(AdmissionNotFoundError):
        await k.guest.redeem(made.token, None)  # 2 sessions used
    k2 = HelpKit()
    m2 = await k2.guest.create(await k2.ctx(), label=None)
    k2.clock.advance(days=15)
    with pytest.raises(AdmissionNotFoundError):
        await k2.guest.redeem(m2.token, None)
    k3 = HelpKit()
    ctx3 = await k3.ctx()
    m3 = await k3.guest.create(ctx3, label=None)
    await k3.guest.revoke(ctx3, m3.record.link.id)
    with pytest.raises(AdmissionNotFoundError):
        await k3.guest.redeem(m3.token, None)
    assert timedelta(days=0) == timedelta()


async def test_respond_file_must_be_helpers_own_with_allowed_purpose() -> None:
    from dataclasses import replace

    from app.modules.admission.application.help import HelpService
    from app.shared.contracts.files import FilePurpose
    from tests.admission.unit.fakes_documents import FakeFiles

    k = HelpKit()
    _, req = await _assigned(k)
    helper = await k.helper_ctx()
    await k.help.accept(helper, req.id)
    files = FakeFiles()
    refs: dict = {}

    async def get(file_id: object) -> object:
        return refs.get(file_id)

    files.get = get  # type: ignore[attr-defined]
    svc = HelpService(
        k.help._uow,
        k.help._access,
        k.clock,
        k.help._limiter,
        files,  # type: ignore[arg-type]
    )
    own = await files.store_bytes(owner_id=HELPER, name="a.pdf", data=b"x")
    foreign = await files.store_bytes(owner_id=STUDENT, name="b.pdf", data=b"x")
    wrong = replace(own, id=new_id(), purpose=FilePurpose.MAIL)
    refs.update({own.id: own, foreign.id: foreign, wrong.id: wrong})
    for bad in (foreign.id, wrong.id, new_id()):
        with pytest.raises(AdmissionNotFoundError):
            await svc.respond(helper, req.id, "t", file_id=bad)
    ok = await svc.respond(helper, req.id, "t", file_id=own.id)
    assert ok.file_id == own.id


async def test_assign_notification_has_student_name_and_get_needs_entitlement() -> None:
    from app.modules.admission.application.help import HelpService
    from tests.admission.unit.fakes_documents import FakeIdentity, user_ref

    k = HelpKit()
    ctx, req = await _assigned(k)
    svc = HelpService(
        k.help._uow,
        k.help._access,
        k.clock,
        k.help._limiter,
        None,  # type: ignore[arg-type]
        FakeIdentity({STUDENT: user_ref(STUDENT)}, {}),
    )
    k.h.notifications.clear()
    await svc.create(ctx, "website", "again", helper_user_id=HELPER)
    [n] = k.h.notifications
    assert n.payload["student_name"] == "Valiev Ali"
    assert (await svc.get(ctx, req.id)).request.id == req.id


async def test_claim_refused_when_another_helper_is_assigned() -> None:
    import dataclasses

    from app.shared.actor import Actor, Role
    from app.shared.ids import new_id

    k = HelpKit()
    k.h.directory[HELPER] = "Mentor M"
    ctx = await k.ctx()
    req = await k.help.create(ctx, "website", "x", item_id=k.item)
    await k.help.assign(ctx, req.id, HELPER)
    made = await k.guest.create(ctx, label=None, help_request_id=req.id)
    intruder = dataclasses.replace(
        ctx, actor=Actor(new_id(), frozenset({Role.STUDENT}))
    )
    with pytest.raises(AdmissionNotFoundError):
        await k.guest.claim(intruder, made.token)
    assert (await k.help.get(ctx, req.id)).request.helper_user_id == HELPER


async def test_claim_is_single_use() -> None:
    import dataclasses

    from app.shared.actor import Actor, Role
    from app.shared.ids import new_id

    k = HelpKit()
    ctx = await k.ctx()
    made = await k.guest.create(ctx, label=None)
    first = dataclasses.replace(ctx, actor=Actor(new_id(), frozenset({Role.STUDENT})))
    second = dataclasses.replace(ctx, actor=Actor(new_id(), frozenset({Role.STUDENT})))
    await k.guest.claim(first, made.token)
    with pytest.raises(AdmissionNotFoundError):
        await k.guest.claim(second, made.token)


async def test_guest_view_scoped_to_linked_item_and_notify_payload_key() -> None:
    k = HelpKit()
    ctx = await k.ctx()
    made = await k.guest.create(ctx, label=None, item_id=k.item)
    sess = await k.guest.redeem(made.token, None)
    await k.guest.view(sess.token, None)
    assert k.h.activity_item_ids == [k.item]
    assert all("request_id" in n.payload for n in k.h.notifications)
    general = await k.guest.create(ctx, label=None)
    sess2 = await k.guest.redeem(general.token, None)
    await k.guest.view(sess2.token, None)
    assert k.h.activity_item_ids[-1] is None
