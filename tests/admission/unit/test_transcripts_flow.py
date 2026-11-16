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
    k = DocKit()
    ctx = await k.w.ctx(k.student, Role.STUDENT)
    req, created = await k.transcripts.request(ctx, "MIT")
    again, created2 = await k.transcripts.request(ctx, "MIT")
    assert created and not created2 and again.id == req.id
    [n] = k.d.notifications
    assert n.type == NotificationType.TRANSCRIPT_REQUESTED
    assert n.user_id == k.officer and n.payload["destination_note"] == "MIT"


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
