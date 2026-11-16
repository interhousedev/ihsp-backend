"""Transcript requests: request, Done with pickup snapshot, Undo, oversight."""

import datetime as dt

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.documents import OfficerSettings
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    PickupNotSetError,
    UndoExpiredError,
)
from app.shared.actor import Role
from app.shared.notifications import NotificationType
from tests.admission.unit.fakes_documents import DocKit
from tests.admission.unit.test_access_policy import _assign

import pytest


async def _officer_ctx(k: DocKit) -> AdmissionContext:
    import dataclasses

    a = _assign("transcript_officer", "all", None)
    k.w.store.assignments[k.officer] = (dataclasses.replace(a, user_id=k.officer),)
    return await k.w.ctx(k.officer, Role.TRANSCRIPT_OFFICER)


async def test_request_notifies_officer_once_and_is_idempotent() -> None:
    from app.shared.ids import new_id

    k = DocKit()
    await _officer_ctx(k)
    # An officer without an assignment to this student is not told.
    k.identity.by_role[Role.TRANSCRIPT_OFFICER].append(new_id())
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    req, created = await k.transcripts.request(ctx, "MIT")
    again, created2 = await k.transcripts.request(ctx, "MIT")
    assert created and not created2 and again.id == req.id
    [n] = k.d.notifications
    assert n.type == NotificationType.TRANSCRIPT_REQUESTED
    assert n.user_id == k.officer and n.payload["destination_note"] == "MIT"


async def test_unrouted_request_reaches_only_overseers_in_scope() -> None:
    k = DocKit()
    k.w.store.assignments[k.staff] = (_assign("counselor_full", "all", None),)
    await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "")
    sent = [
        n.user_id
        for n in k.d.notifications
        if n.type == NotificationType.TRANSCRIPT_UNROUTED
    ]
    assert sent == [k.staff]


async def test_unrouted_request_skips_overseers_out_of_scope() -> None:
    k = DocKit()
    await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "")
    assert not [
        n for n in k.d.notifications if n.type == NotificationType.TRANSCRIPT_UNROUTED
    ]


async def test_remind_reaches_only_officers_in_scope() -> None:
    from app.shared.ids import new_id

    k = DocKit()
    await _officer_ctx(k)
    k.identity.by_role[Role.TRANSCRIPT_OFFICER].append(new_id())
    k.w.store.assignments[k.staff] = (_assign("counselor_full", "all", None),)
    req, _ = await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "")
    k.d.notifications.clear()
    await k.transcripts.remind(await k.w.ctx(k.staff, Role.COUNSELOR), req.id)
    sent = [
        n.user_id
        for n in k.d.notifications
        if n.type == NotificationType.TRANSCRIPT_REMINDER
    ]
    assert sent == [k.officer]


async def test_done_without_pickup_raises() -> None:
    k = DocKit()
    req, _ = await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "")
    with pytest.raises(PickupNotSetError):
        await k.transcripts.done(await _officer_ctx(k), req.id)


async def test_done_snapshots_pickup_and_queues_delayed_notice() -> None:
    k = DocKit()
    k.w.store.runtime = {"pickup_location": {"ru": "Каб. 5", "en": "Room 5"}}
    req, _ = await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "")
    k.d.notifications.clear()
    res = await k.transcripts.done(await _officer_ctx(k), req.id)
    assert not res.already and res.request.status == "ready"
    assert res.request.pickup_location_snapshot == "Каб. 5"
    [n] = k.d.notifications
    assert n.type == NotificationType.TRANSCRIPT_READY
    assert n.scheduled_at == res.request.undo_until
    assert n.payload["pickup_location"] == "Каб. 5"
    again = await k.transcripts.done(await _officer_ctx(k), req.id)
    assert again.already


async def test_officer_own_pickup_wins_over_runtime() -> None:
    k = DocKit()
    k.w.store.runtime = {"pickup_location": {"ru": "Каб. 5"}}
    k.d.officers[k.officer] = OfficerSettings(k.officer, {"ru": "Каб. 9"})
    req, _ = await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "")
    res = await k.transcripts.done(await _officer_ctx(k), req.id)
    assert res.request.pickup_location_snapshot == "Каб. 9"


async def test_undo_cancels_pending_notice() -> None:
    k = DocKit()
    k.w.store.runtime = {"pickup_location": {"ru": "Каб. 5"}}
    req, _ = await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "")
    ctx = await _officer_ctx(k)
    res = await k.transcripts.done(ctx, req.id)
    k.d.pending_keys.add(res.request.ready_key())
    back = await k.transcripts.undo(ctx, req.id)
    assert back.status == "requested" and back.pickup_location_snapshot is None
    assert not k.d.pending_keys


async def test_undo_after_notice_sent_is_expired() -> None:
    k = DocKit()
    k.w.store.runtime = {"pickup_location": {"ru": "Каб. 5"}}
    req, _ = await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "")
    ctx = await _officer_ctx(k)
    await k.transcripts.done(ctx, req.id)
    with pytest.raises(UndoExpiredError):  # notice no longer pending
        await k.transcripts.undo(ctx, req.id)


async def test_undo_after_window_is_expired() -> None:
    k = DocKit()
    k.w.store.runtime = {"pickup_location": {"ru": "Каб. 5"}}
    req, _ = await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "")
    ctx = await _officer_ctx(k)
    res = await k.transcripts.done(ctx, req.id)
    k.d.pending_keys.add(res.request.ready_key())
    res.request.undo_until = k.clock.now() - dt.timedelta(seconds=1)
    with pytest.raises(UndoExpiredError):
        await k.transcripts.undo(ctx, req.id)


async def test_student_cannot_fulfil() -> None:
    k = DocKit()
    k.w.store.runtime = {"pickup_location": {"ru": "x"}}
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    req, _ = await k.transcripts.request(ctx, "")
    with pytest.raises(AdmissionForbiddenError):
        await k.transcripts.done(ctx, req.id)


async def test_admin_sets_and_reads_own_pickup_and_it_is_cleaned() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.officer, Role.ADMIN)
    saved = await k.transcripts.set_pickup(
        ctx, {"ru": "  Каб.   5 ", "en": "", "xx": "bad", "uz": "5-xona"}
    )
    assert saved.pickup_location == {"ru": "Каб. 5", "uz": "5-xona"}
    got = await k.transcripts.get_officer_settings(ctx)
    assert got.pickup_location == saved.pickup_location
    assert await k.transcripts.pickup_for(ctx) == saved.pickup_location


async def test_student_cannot_set_pickup() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    with pytest.raises(AdmissionForbiddenError):
        await k.transcripts.set_pickup(ctx, {"ru": "x"})


async def test_officer_queue_and_overview_audit_once_per_list() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    await k.transcripts.request(ctx, "MIT")
    officer = await _officer_ctx(k)
    k.w.store.audit.clear()
    rows = await k.transcripts.officer_queue(officer)
    assert len(rows) == 1
    assert [e.action for e in k.w.store.audit] == ["transcript.listed"]


async def test_officer_queue_filters_by_status() -> None:
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    req, _ = await k.transcripts.request(ctx, "MIT")
    officer = await _officer_ctx(k)
    await k.transcripts.set_pickup(officer, {"en": "Room 1"})
    await k.transcripts.done(officer, req.id, lock_version=req.lock_version)
    assert await k.transcripts.officer_queue(officer) == []
    ready = await k.transcripts.officer_queue(officer, "ready")
    assert [r.request.id for r in ready] == [req.id]
    assert await k.transcripts.officer_queue(officer, "cancelled") == []


async def test_scan_upload_returns_view_and_notifies_staff_not_student() -> None:
    k = DocKit()
    req, _ = await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "")
    k.d.notifications.clear()
    view = await k.transcripts.upload_scan(
        await _officer_ctx(k), req.id, name="t.pdf", data=b"%PDF-1"
    )
    assert view.doc.student_id == k.student and view.versions
    sent = [n for n in k.d.notifications if n.type.name == "TRANSCRIPT_SCAN_UPLOADED"]
    assert all(n.user_id != k.student for n in sent)


async def test_scan_upload_notifies_only_staff_in_scope() -> None:
    from app.shared.ids import new_id

    k = DocKit()
    k.w.store.assignments[k.staff] = (_assign("counselor_full", "all", None),)
    stranger = new_id()
    k.identity.by_role[Role.COUNSELOR].append(stranger)
    req, _ = await k.transcripts.request(await k.w.ctx(k.student, Role.STUDENT), "")
    k.d.notifications.clear()
    await k.transcripts.upload_scan(
        await _officer_ctx(k), req.id, name="t.pdf", data=b"%PDF-1"
    )
    sent = [
        n.user_id
        for n in k.d.notifications
        if n.type == NotificationType.TRANSCRIPT_SCAN_UPLOADED
    ]
    # The counselor without an assignment to this student is not told.
    assert sent == [k.staff]


async def _read_with(data: bytes) -> bytes:
    import io
    from types import SimpleNamespace

    from app.interfaces.http.v1.admission.routes_documents import _read

    from fastapi import UploadFile

    k = DocKit()
    container = SimpleNamespace(admission=SimpleNamespace(documents=k.docs))
    ctx = SimpleNamespace(user_id=k.student)
    file = UploadFile(io.BytesIO(data), filename="a")
    return await _read(container, ctx, file)  # type: ignore[arg-type]


MB = 1024 * 1024


async def test_route_read_rejects_over_25_mb_and_accepts_24() -> None:
    from app.modules.files.domain.errors import FileTooLargeError

    ok = b"%PDF-" + b"0" * (24 * MB)
    assert await _read_with(ok) == ok
    with pytest.raises(FileTooLargeError):
        await _read_with(b"%PDF-" + b"0" * (26 * MB))


async def test_route_read_rejects_wrong_type() -> None:
    from app.modules.files.domain.errors import TypeNotAllowedError

    with pytest.raises(TypeNotAllowedError):
        await _read_with(b"GIF89a" + b"0" * 10)
    assert await _read_with(b"\x89PNG\r\n\x1a\nxx") == b"\x89PNG\r\n\x1a\nxx"


async def test_planner_uses_its_own_weekly_limit() -> None:
    import re
    from pathlib import Path
    from types import SimpleNamespace

    from app.modules.admission import wiring
    from app.settings import LimitsSettings
    from app.shared.limits import StaticLimits

    assert LimitsSettings().admit_opportunity_plan_per_week == 3
    src = Path(wiring.__file__).read_text()
    block = re.search(r"OpportunityPlanner\((.*?)\n\s*\)", src, re.S)
    assert block is not None
    assert "admit_opportunity_plan_per_week" in block.group(1)
    assert "admit_goal_plan_per_week" not in block.group(1)
    deps = SimpleNamespace(
        effective_limits=StaticLimits(
            LimitsSettings(
                admit_opportunity_plan_per_week=7, admit_goal_plan_per_week=2
            )
        )
    )
    quota = wiring._quota_of(
        deps, "admit_opportunity_plan_per_week"  # type: ignore[arg-type]
    )
    assert await quota(DocKit().student) == 7
