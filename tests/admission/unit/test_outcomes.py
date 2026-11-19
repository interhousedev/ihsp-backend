"""Outcome aggregation (name privacy) and nudge scheduling."""

import dataclasses
import datetime as dt
from types import SimpleNamespace
from typing import Any, Self
from uuid import UUID

from app.modules.admission.application.access import VIEWED
from app.modules.admission.application.nudges import NudgeService
from app.modules.admission.application.outcomes import OutcomeService
from app.modules.admission.domain.documents import Deadline, ReminderPrefs
from app.modules.admission.domain.institution_brand import InstitutionBrand
from app.modules.admission.domain.outcomes import (
    NudgeTarget,
    Outcome,
    aggregate,
    plan_nudges,
)
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW
from tests.admission.unit.fakes_documents import DocState, FakeDeadlines
from tests.admission.unit.test_access_policy import (
    OTHER,
    STAFF,
    STUDENT,
    World,
    _assign,
)

INST, S1, S2, S3 = new_id(), new_id(), new_id(), new_id()
UTC = dt.UTC


def _outcome(student: UUID, status: str, share: bool) -> Outcome:
    return Outcome(
        new_id(), student, INST, 2026, "rd", status, share  # type: ignore[arg-type]
    )


def _deadline(
    due: dt.datetime, round_: str = "RD", status: str = "confirmed"
) -> Deadline:
    return Deadline(
        new_id(),
        INST,
        2026,
        round_,
        precision="instant",
        instant_utc=due,
        status=status,  # type: ignore[arg-type]
    )


def test_aggregate_lists_only_opted_in_names() -> None:
    rows = [
        _outcome(S1, "accepted", True),
        _outcome(S2, "enrolled", False),
        _outcome(S3, "rejected", False),
    ]
    names = {S1: "Aliev Ali", S2: "Karimova Zarina", S3: "Umarov Bek"}
    [tally] = aggregate(rows, names)
    assert (tally.reported, tally.accepted) == (3, 2)
    assert tally.by_status == {"accepted": 1, "enrolled": 1, "rejected": 1}
    assert [n.name for n in tally.names] == ["Aliev Ali"]


def test_aggregate_staff_sees_every_name_with_shared_flag() -> None:
    rows = [_outcome(S1, "accepted", True), _outcome(S2, "applied", False)]
    names = {S1: "Aliev Ali", S2: "Karimova Zarina"}
    [tally] = aggregate(rows, names, reveal_all=True)
    assert {(n.name, n.shared) for n in tally.names} == {
        ("Aliev Ali", True),
        ("Karimova Zarina", False),
    }


def test_aggregate_never_lists_unresolved_names() -> None:
    [tally] = aggregate([_outcome(S1, "applied", True)], {}, reveal_all=True)
    assert tally.reported == 1 and tally.names == []


def test_nudge_windows_and_keys() -> None:
    target = [NudgeTarget(S1, INST)]
    for days, kind in ((30, "d30"), (7, "d7"), (0, "d0")):
        due = NOW + dt.timedelta(days=days, hours=1)
        [n] = plan_nudges(NOW, target, [_deadline(due)], set())
        assert n.kind == kind and n.dedupe_key.endswith(kind)
    assert (
        plan_nudges(NOW, target, [_deadline(NOW + dt.timedelta(days=15))], set()) == []
    )
    assert (
        plan_nudges(NOW, target, [_deadline(NOW - dt.timedelta(hours=1))], set()) == []
    )


def test_unconfirmed_deadline_is_not_nudged() -> None:
    due = NOW + dt.timedelta(days=7, hours=1)
    assert (
        plan_nudges(
            NOW, [NudgeTarget(S1, INST)], [_deadline(due, status="predicted")], set()
        )
        == []
    )


def test_result_question_after_sixty_days_once_and_skipped_when_reported() -> None:
    due = NOW - dt.timedelta(days=60, hours=1)
    target = [NudgeTarget(S1, INST)]
    [n] = plan_nudges(NOW, target, [_deadline(due)], set())
    assert n.kind == "result" and n.dedupe_key.endswith(":2026:result")
    assert plan_nudges(NOW, target, [_deadline(due)], {(S1, INST, 2026)}) == []
    early = NOW - dt.timedelta(days=30)
    assert plan_nudges(NOW, target, [_deadline(early)], set()) == []


def test_result_question_uses_decision_date_plus_one_day() -> None:
    due = NOW - dt.timedelta(days=20)
    decision = NOW - dt.timedelta(days=1)
    [n] = plan_nudges(NOW, [NudgeTarget(S1, INST, decision)], [_deadline(due)], set())
    assert n.kind == "result"
    assert plan_nudges(NOW, [NudgeTarget(S1, INST)], [_deadline(due)], set()) == []


class _Outcomes:
    def __init__(self, targets: list[NudgeTarget]) -> None:
        self.targets = targets

    async def nudge_targets(self) -> list[NudgeTarget]:
        return self.targets

    async def reported_keys(self, ids: Any) -> set[tuple[UUID, UUID, int]]:
        return set()


class _Uow:
    def __init__(self, d: DocState, targets: list[NudgeTarget]) -> None:
        self.deadlines = FakeDeadlines(d)
        self.outcomes = _Outcomes(targets)
        self.notify = lambda *drafts: d.notifications.extend(drafts)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _Clock:
    def now(self) -> dt.datetime:
        return NOW


def _service(d: DocState, due: dt.datetime) -> NudgeService:
    deadline = _deadline(due)
    d.deadlines[deadline.id] = dataclasses.replace(deadline)
    d.institution_names[INST] = "MIT"
    return NudgeService(
        lambda: _Uow(d, [NudgeTarget(S1, INST)]), _Clock()  # type: ignore[arg-type]
    )


async def test_service_queues_d7_with_payload() -> None:
    d = DocState()
    svc = _service(d, NOW + dt.timedelta(days=7, hours=1))
    d.prefs[S1] = ReminderPrefs(S1, quiet_from=dt.time(0), quiet_to=dt.time(0))
    assert await svc.run() == 1
    [n] = d.notifications
    assert n.payload["kind"] == "d7" and n.payload["institution"] == "MIT"
    assert n.scheduled_at is None


async def test_service_respects_offset_prefs_and_quiet_hours() -> None:
    d = DocState()
    svc = _service(d, NOW + dt.timedelta(days=7, hours=1))
    d.prefs[S1] = ReminderPrefs(S1, offsets_days=(30,))
    assert await svc.run() == 0  # 7 days switched off
    d2 = DocState()
    svc2 = _service(d2, NOW + dt.timedelta(hours=3))  # d0 is always sent
    d2.prefs[S1] = ReminderPrefs(S1, quiet_from=dt.time(8), quiet_to=dt.time(20))
    assert await svc2.run() == 1
    assert d2.notifications[0].scheduled_at is not None  # pushed past quiet hours


class _Summary:
    """Unit of work for `OutcomeService.summary` over a fixed set of reports."""

    def __init__(self, rows: list[Outcome], audit: list[Any]) -> None:
        self.outcomes = self
        self.deadlines = self
        self.access = self
        self.rows, self.events = rows, audit

    async def all(self, **_: Any) -> list[Outcome]:
        return self.rows

    async def institution_names(self, ids: Any) -> dict[UUID, str]:
        return dict.fromkeys(ids, "MIT")

    async def institution_brands(self, ids: Any) -> dict[UUID, InstitutionBrand]:
        return dict.fromkeys(ids, InstitutionBrand("MIT"))

    def audit(self, event: Any) -> None:
        self.events.append(event)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _Directory:
    async def get_users(self, ids: Any) -> dict[UUID, Any]:
        return {i: SimpleNamespace(first_name="F", last_name=str(i)) for i in ids}


def _summary_kit() -> tuple[World, OutcomeService, list[Any]]:
    world = World()
    events: list[Any] = []
    rows = [
        _student_outcome(STUDENT, share=False),
        _student_outcome(OTHER, share=False),
        _student_outcome(S1, share=True),
    ]
    svc = OutcomeService(
        lambda: _Summary(rows, events),  # type: ignore[arg-type,return-value]
        world.policy,
        _Directory(),  # type: ignore[arg-type]
    )
    return world, svc, events


def _student_outcome(student: UUID, *, share: bool) -> Outcome:
    return Outcome(new_id(), student, INST, 2026, "rd", "accepted", share)


def _named(summary: Any) -> set[str]:
    return {n.name for t in summary.tallies for n in t.names}


async def test_summary_unassigned_staff_sees_only_opted_in_names() -> None:
    world, svc, events = _summary_kit()
    mentor = await world.ctx(STAFF, Role.MENTOR)
    summary = await svc.summary(mentor)
    assert summary.reported == 3
    assert _named(summary) == {f"{S1} F"}
    assert events == []


async def test_summary_reveals_only_assigned_students_with_audit() -> None:
    world, svc, events = _summary_kit()
    world.store.assignments[STAFF] = (_assign("counselor_full", "student", STUDENT),)
    counselor = await world.ctx(STAFF, Role.COUNSELOR)
    assert _named(await svc.summary(counselor)) == {f"{S1} F", f"{STUDENT} F"}
    assert [(e.action, e.student_id) for e in events] == [(VIEWED, STUDENT)]


async def test_summary_admin_sees_every_name() -> None:
    world, svc, events = _summary_kit()
    admin = await world.ctx(new_id(), Role.ADMIN, Role.COUNSELOR)
    assert _named(await svc.summary(admin)) == {
        f"{S1} F",
        f"{STUDENT} F",
        f"{OTHER} F",
    }
    assert {e.student_id for e in events} == {STUDENT, OTHER}
