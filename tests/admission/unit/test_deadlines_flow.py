"""Deadlines: permissions, versioning, milestones and the reminder job."""

import dataclasses
import datetime as dt
import zoneinfo

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.deadlines import DeadlineInput
from app.modules.admission.domain.documents import (
    Milestone,
    ReminderPrefs,
    confirmed_instant,
    shift_out_of_quiet,
)
from app.modules.admission.domain.errors import AdmissionForbiddenError
from app.shared.actor import Role
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.admission.unit.fakes import NOW
from tests.admission.unit.fakes_documents import DocKit, DocUow
from tests.admission.unit.test_access_policy import _assign

import pytest

INST = new_id()
CONFIRMED = DeadlineInput(
    status="confirmed",
    precision="date_only",
    source_tz="Asia/Tashkent",
    local_date=dt.date(2026, 3, 20),
    cutoff_time=dt.time(23, 59),
)


async def _admin(k: DocKit) -> AdmissionContext:
    return await k.w.ctx(k.staff, Role.ADMIN)


async def test_student_and_plain_counselor_cannot_manage() -> None:
    k = DocKit()
    student = await k.w.ctx(k.student, Role.STUDENT)
    with pytest.raises(AdmissionForbiddenError):
        await k.deadlines.create(
            student, institution_id=INST, cycle=2026, round="RD", data=CONFIRMED
        )


async def test_documents_counselor_can_manage_and_edit_versions() -> None:
    k = DocKit()
    a = _assign("counselor_documents", "all", None)
    k.w.store.assignments[k.staff] = (dataclasses.replace(a, user_id=k.staff),)
    ctx = await k.w.ctx(k.staff, Role.COUNSELOR)
    d1 = await k.deadlines.create(
        ctx, institution_id=INST, cycle=2026, round="RD", data=CONFIRMED
    )
    d2 = await k.deadlines.edit(
        ctx, d1.id, DeadlineInput(local_date=dt.date(2026, 3, 25))
    )
    assert d2.version == 2 and d2.local_date == dt.date(2026, 3, 25)
    assert d2.cutoff_time == dt.time(23, 59)
    assert k.d.deadlines[d1.id].superseded_by == d2.id
    assert [x.id for x in await k.deadlines.listing(ctx, institution_id=INST)] == [
        d2.id
    ]


async def test_patch_with_explicit_null_clears_nullable_fields() -> None:
    k = DocKit()
    ctx = await _admin(k)
    d1 = await k.deadlines.create(
        ctx,
        institution_id=INST,
        cycle=2026,
        round="RD",
        data=dataclasses.replace(CONFIRMED, source_text="site"),
    )
    patch = {"local_date": None, "source_text": None}
    d2 = await k.deadlines.edit(ctx, d1.id, DeadlineInput.from_patch(patch))
    assert d2.local_date is None and d2.source_text is None
    assert d2.cutoff_time == dt.time(23, 59)
    # a field missing from the patch is kept
    d3 = await k.deadlines.edit(ctx, d2.id, DeadlineInput.from_patch({}))
    assert d3.status == "confirmed"


async def test_remove_runs_in_one_unit_of_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    k = DocKit()
    ctx = await _admin(k)
    d1 = await k.deadlines.create(
        ctx, institution_id=INST, cycle=2026, round="RD", data=CONFIRMED
    )
    commits: list[int] = []
    real = DocUow.commit

    async def counting(self: DocUow) -> None:
        commits.append(1)
        await real(self)

    monkeypatch.setattr(DocUow, "commit", counting)
    await k.deadlines.remove(ctx, d1.id)
    assert len(commits) == 1


async def test_edit_moves_milestones_and_notifies_students() -> None:
    k = DocKit()
    ctx = await _admin(k)
    d1 = await k.deadlines.create(
        ctx, institution_id=INST, cycle=2026, round="RD", data=CONFIRMED
    )
    m = Milestone(new_id(), new_id(), "deadline", NOW, d1.id, 1)
    k.d.milestones[m.id] = m
    k.d.milestone_owner[m.id] = k.student
    d2 = await k.deadlines.edit(ctx, d1.id, DeadlineInput(status="predicted"))
    moved = k.d.milestones[m.id]
    assert moved.deadline_id == d2.id and moved.deadline_version == 2
    assert moved.predicted and moved.due_utc is None
    [n] = k.d.notifications
    assert n.type == NotificationType.DEADLINE_CHANGED and n.user_id == k.student


async def _milestone(k: DocKit, due: dt.datetime, predicted: bool = False) -> Milestone:
    ctx = await _admin(k)
    d = await k.deadlines.create(
        ctx, institution_id=INST, cycle=2026, round="RD", data=CONFIRMED
    )
    m = Milestone(new_id(), new_id(), "deadline", due, d.id, 1, predicted)
    k.d.milestones[m.id] = m
    k.d.milestone_owner[m.id] = k.student
    return m


async def test_reminder_job_selects_fired_offsets_once() -> None:
    k = DocKit()
    await _milestone(k, NOW + dt.timedelta(days=7, hours=-1))  # 7-day mark passed
    k.d.prefs[k.student] = ReminderPrefs(
        k.student, quiet_from=dt.time(0), quiet_to=dt.time(0)
    )
    assert await k.deadlines.run_reminders() == 1
    assert await k.deadlines.run_reminders() == 0  # deduped
    [n] = k.d.notifications
    assert n.type == NotificationType.ADMISSION_DEADLINE_REMINDER
    assert n.payload["days"] == "7"


async def test_reminder_job_skips_predicted_and_far_milestones() -> None:
    k = DocKit()
    await _milestone(k, NOW + dt.timedelta(days=7, hours=-1), predicted=True)
    await _milestone(k, NOW + dt.timedelta(days=90))
    assert await k.deadlines.run_reminders() == 0
    assert k.d.notifications == []


async def test_reminder_inside_quiet_hours_is_delayed() -> None:
    k = DocKit()  # NOW is 14:00 Tashkent; make quiet cover it
    await _milestone(k, NOW + dt.timedelta(days=7, hours=-1))
    k.d.prefs[k.student] = ReminderPrefs(
        k.student, quiet_from=dt.time(8), quiet_to=dt.time(20)
    )
    await k.deadlines.run_reminders()
    [n] = k.d.notifications
    assert n.scheduled_at is not None and n.scheduled_at > NOW


def test_confirmed_instant_requires_certainty() -> None:
    from app.modules.admission.domain.documents import Deadline

    d = Deadline(new_id(), INST, 2026, "RD", status="predicted")
    assert confirmed_instant(d) is None
    d = Deadline(
        new_id(),
        INST,
        2026,
        "RD",
        status="confirmed",
        local_date=dt.date(2026, 3, 20),
        cutoff_time=dt.time(23, 59),
    )
    assert confirmed_instant(d) is None  # no zone
    d.source_tz = "Asia/Tashkent"
    assert confirmed_instant(d) == dt.datetime(
        2026, 3, 20, 23, 59, tzinfo=zoneinfo.ZoneInfo("Asia/Tashkent")
    )


def test_shift_out_of_quiet_wraps_midnight() -> None:
    tz = zoneinfo.ZoneInfo("Asia/Tashkent")
    late = dt.datetime(2026, 3, 2, 23, 0, tzinfo=tz)
    out = shift_out_of_quiet(late, dt.time(22), dt.time(8)).astimezone(tz)
    assert out == dt.datetime(2026, 3, 3, 8, 0, tzinfo=tz)
