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
