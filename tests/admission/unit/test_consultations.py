"""Consultation state machine and answers persistence (in-memory fakes)."""

import dataclasses
import datetime as dt
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import VIEWED
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.consultations import (
    ConsultationDraft,
    ConsultationService,
)
from app.modules.admission.application.document_process import DocumentProcessService
from app.modules.admission.application.profile_details import ProfileDetailsService
from app.modules.admission.domain.consultations import MAX_ACTIVE, Consultation
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    InvalidAnswerError,
    InvalidTransitionError,
)
from app.modules.admission.domain.profile_details import Interests, QuizAnswers
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeUow
from tests.admission.unit.test_access_policy import (
    OTHER,
    STAFF,
    STUDENT,
    World,
    _assign,
)
from tests.fakes.clock import FixedClock

import pytest

pytestmark = pytest.mark.asyncio

SOON = NOW + dt.timedelta(days=2)
LATER = NOW + dt.timedelta(days=3)


class _Consults:
    def __init__(self) -> None:
        self.rows: dict[UUID, Consultation] = {}

    async def add(self, c: Consultation) -> Consultation:
        c = dataclasses.replace(c, created_at=NOW, updated_at=NOW)
        self.rows[c.id] = c
        return c

    async def get(self, cid: UUID) -> Consultation | None:
        found = self.rows.get(cid)
        return dataclasses.replace(found) if found else None

    async def save(self, c: Consultation) -> Consultation:
        self.rows[c.id] = dataclasses.replace(c, lock_version=c.lock_version + 1)
        return self.rows[c.id]

    async def of_student(self, student_id: UUID) -> list[Consultation]:
        return [c for c in self.rows.values() if c.student_id == student_id]

    async def count_active(self, student_id: UUID) -> int:
        return sum(
            1
            for c in self.rows.values()
            if c.student_id == student_id
            and c.status in ("requested", "proposed", "accepted")
        )

    async def for_staff(
        self,
        kinds: Any,
        staff_id: UUID,
        statuses: tuple[str, ...],
        *,
        all_staff: bool,
    ) -> list[Consultation]:
        return [
            c
            for c in self.rows.values()
            if c.status in statuses
            and (all_staff or c.with_kind in kinds)
            and (all_staff or c.staff_id in (None, staff_id))
        ]


class _Details:
    def __init__(self) -> None:
        self.interests: Interests = Interests()
        self.quizzes: dict[str, QuizAnswers] = {}

    async def get_interests(self, student_id: UUID) -> Interests:
        return self.interests

    async def save_interests(
        self, student_id: UUID, interests: Interests, now: dt.datetime
    ) -> None:
        self.interests = interests

    async def get_quiz(self, student_id: UUID, quiz: str) -> QuizAnswers | None:
        return self.quizzes.get(quiz)

    async def save_quiz(self, answers: QuizAnswers, now: dt.datetime) -> None:
        self.quizzes[answers.quiz] = answers

    async def completed_quizzes(self, student_id: UUID) -> frozenset[str]:
        return frozenset(k for k, q in self.quizzes.items() if q.completed)


class _Profiles:
    async def get(self, student_id: UUID) -> None:
        return None

    async def get_words(self, student_id: UUID) -> None:
        return None


class _Items:
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    async def list_for(self, student_id: UUID) -> list[object]:
        return []

    async def get(self, item_id: UUID) -> Any:
        return self.rows.get(item_id)


class _Essays:
    def __init__(self) -> None:
        self.rows: dict[UUID, Any] = {}

    async def get(self, essay_id: UUID) -> Any:
        return self.rows.get(essay_id)


class _Access:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def audit(self, event: Any) -> None:
        self.events.append(event)


class _Uow:
    def __init__(self, kit: "Kit") -> None:
        self.consultations = kit.consults
        self.profile_details = kit.details
        self.profiles = _Profiles()
        self.items = kit.items
        self.essays = kit.essays
        self.access = kit.access
        self.staff = FakeUow(kit.world.store).staff
        self._kit = kit

    def notify(self, *drafts: Any) -> None:
        self._kit.notified.extend(drafts)

    async def __aenter__(self) -> "_Uow":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class Kit:
    def __init__(self) -> None:
        self.world = World()
        self.consults = _Consults()
        self.details = _Details()
        self.items = _Items()
        self.essays = _Essays()
        self.access = _Access()
        self.notified: list[Any] = []
        factory: Any = lambda: _Uow(self)  # noqa: E731
        clock = FixedClock(NOW)
        self.svc = ConsultationService(factory, self.world.policy, clock)
        self.profile = ProfileDetailsService(factory, self.world.policy, clock)

    async def counselor(self, ref: UUID = STUDENT) -> AdmissionContext:
        """A counselor whose live assignment covers `ref`."""
        self.world.store.assignments[STAFF] = (
            _assign("counselor_full", "student", ref),
        )
        return await self.world.ctx(STAFF, Role.COUNSELOR)


def _draft(**kw: Any) -> ConsultationDraft:
    base: dict[str, Any] = {
        "with_kind": "counselor",
        "topic": "Common App essay",
        "format": "online",
        "linked_kind": "essay",
        "preferred_times": (SOON, LATER),
    }
    return ConsultationDraft(**{**base, **kw})


async def test_request_accept_complete() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    staff = await k.counselor()
    made = await k.svc.request(student, _draft())
    cid = made.consultation.id
    assert made.consultation.status == "requested"
    assert made.actions == ("cancel",)
    assert [v.consultation.id for v in await k.svc.queue(staff)] == [cid]

    accepted = await k.svc.accept(staff, cid, None, "Room 3")
    assert accepted.consultation.status == "accepted"
    assert accepted.consultation.scheduled_at == SOON
    assert accepted.consultation.staff_id == STAFF

    done = await k.svc.complete(staff, cid, "Reworked the intro")
    assert done.consultation.status == "completed"
    assert done.consultation.staff_notes == "Reworked the intro"
    with pytest.raises(InvalidTransitionError):
        await k.svc.cancel(student, cid)


async def test_propose_then_student_confirms_or_rejects() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    staff = await k.counselor()
    cid = (await k.svc.request(student, _draft())).consultation.id
    proposed = await k.svc.propose(staff, cid, LATER, "Zoom")
    assert proposed.consultation.status == "proposed"
    assert (await k.svc.mine(student))[0].actions == ("confirm", "reject", "cancel")

    back = await k.svc.reject(student, cid)
    assert back.consultation.status == "requested"
    assert back.consultation.staff_id is None

    await k.svc.propose(staff, cid, LATER, "Zoom")
    confirmed = await k.svc.confirm(student, cid)
    assert confirmed.consultation.status == "accepted"
    assert confirmed.consultation.scheduled_at == LATER


async def test_reject_notifies_the_proposing_staff_member() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    staff = await k.counselor()
    cid = (await k.svc.request(student, _draft())).consultation.id
    await k.svc.propose(staff, cid, LATER, "Zoom")
    k.notified.clear()
    await k.svc.reject(student, cid)
    assert [(n.user_id, n.payload["event"]) for n in k.notified] == [
        (STAFF, "rejected")
    ]


async def test_illegal_transitions() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    staff = await k.counselor()
    cid = (await k.svc.request(student, _draft())).consultation.id
    with pytest.raises(InvalidTransitionError):
        await k.svc.confirm(student, cid)
    with pytest.raises(InvalidTransitionError):
        await k.svc.complete(staff, cid, "x")
    declined = await k.svc.decline(staff, cid, "Not my area")
    assert declined.consultation.status == "declined"
    with pytest.raises(InvalidTransitionError):
        await k.svc.accept(staff, cid, SOON, "")


async def test_past_time_and_active_limit_rejected() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    staff = await k.counselor()
    cid = (await k.svc.request(student, _draft())).consultation.id
    with pytest.raises(Exception):  # noqa: B017 - a domain validation error
        await k.svc.propose(staff, cid, NOW - dt.timedelta(days=1), "")
    for _ in range(MAX_ACTIVE - 1):
        await k.svc.request(student, _draft())
    with pytest.raises(Exception):  # noqa: B017
        await k.svc.request(student, _draft())


async def test_access_is_scoped() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    other = await k.world.ctx(OTHER, Role.STUDENT)
    mentor = await k.world.ctx(new_id(), Role.MENTOR)
    cid = (await k.svc.request(student, _draft())).consultation.id
    with pytest.raises(AdmissionNotFoundError):
        await k.svc.cancel(other, cid)
    with pytest.raises(AdmissionNotFoundError):
        await k.svc.accept(mentor, cid, SOON, "")  # counselor request
    with pytest.raises(Exception):  # noqa: B017 - not staff at all
        await k.svc.queue(other)
    assert await k.svc.queue(mentor) == []


async def test_quiz_answers_round_trip_with_multi_choice() -> None:
    k = Kit()
    ctx = await k.world.ctx(STUDENT, Role.STUDENT)
    assert (await k.profile.get_quiz(ctx, "career")).answers == {}
    answers = {"q1": "a", "q2": ["x", "y", "x"], "q3": 4, "q4": True}
    await k.profile.put_quiz(ctx, "career", answers, True)
    got = await k.profile.get_quiz(ctx, "career")
    assert got.completed
    assert got.answers == {"q1": "a", "q2": ["x", "y"], "q3": 4, "q4": True}
    assert (await k.profile.get_quiz(ctx, "algorithm")).answers == {}
    with pytest.raises(InvalidAnswerError):
        await k.profile.put_quiz(ctx, "career", {"q": {"nested": 1}}, False)
    with pytest.raises(AdmissionNotFoundError):
        await k.profile.get_quiz(ctx, "nope")


async def test_interests_and_completion() -> None:
    k = Kit()
    ctx = await k.world.ctx(STUDENT, Role.STUDENT)
    start = await k.profile.overview(ctx, "en")
    assert start.percent == 0 and len(start.missing) == 7
    with pytest.raises(InvalidAnswerError):
        await k.profile.put_interests(ctx, ["underwater_basketry"], [])
    await k.profile.put_interests(ctx, ["writing", "writing"], ["tutoring"])
    await k.profile.put_quiz(ctx, "algorithm", {"q": "a"}, True)
    now = await k.profile.overview(ctx, "ru")
    assert now.interests == Interests(("writing",), ("tutoring",))
    assert now.percent == round(100 * 3 / 7)
    keys = {m.key for m in now.missing}
    assert "career_quiz" in keys and "algorithm_quiz" not in keys
    assert all(m.label for m in now.missing)


async def test_linked_item_must_belong_to_the_student() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    mine, theirs, essay = new_id(), new_id(), new_id()
    k.items.rows[mine] = SimpleNamespace(student_id=STUDENT)
    k.items.rows[theirs] = SimpleNamespace(student_id=OTHER)
    k.essays.rows[essay] = SimpleNamespace(student_id=OTHER)
    ok = await k.svc.request(student, _draft(linked_kind="project", linked_id=mine))
    assert ok.consultation.linked_id == mine
    for kind, lid in (("project", theirs), ("essay", essay), ("activity", new_id())):
        with pytest.raises(AdmissionNotFoundError):
            await k.svc.request(student, _draft(linked_kind=kind, linked_id=lid))
    with pytest.raises(AdmissionNotFoundError):
        await k.svc.request(student, _draft(linked_kind="other", linked_id=mine))


async def test_steps_are_audited_and_notified() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    staff = await k.counselor()
    cid = (await k.svc.request(student, _draft())).consultation.id
    assert k.notified == []
    await k.svc.accept(staff, cid, None, "Room 3")
    assert [n.user_id for n in k.notified] == [STUDENT]
    assert k.notified[0].payload["kind"] == "consultation"
    assert k.notified[0].payload["event"] == "accepted"
    await k.svc.cancel(student, cid)
    assert k.notified[-1].user_id == STAFF
    assert [e.action for e in k.access.events] == [
        "consultation.requested",
        "consultation.accepted",
        "consultation.cancelled",
    ]


async def test_document_process_reports_own_status() -> None:
    k = Kit()
    ctx = await k.world.ctx(STUDENT, Role.STUDENT)

    class _Transcripts:
        async def of_student(self, student_id: UUID) -> list[Any]:
            return [SimpleNamespace(status="requested")]

    class _Documents:
        async def for_students(self, ids: list[UUID]) -> list[Any]:
            return [SimpleNamespace(kind="rec")]

    class _ProcUow:
        transcripts = _Transcripts()
        documents = _Documents()

        async def __aenter__(self) -> "_ProcUow":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    factory: Any = lambda: _ProcUow()  # noqa: E731
    steps = await DocumentProcessService(factory, k.world.policy).steps(ctx, "en")
    by_key = {s.key: s for s in steps}
    assert [s.key for s in steps][:2] == ["transcript", "school_profile"]
    assert by_key["transcript"].status == "requested"
    assert by_key["recommendations"].status == "ready"
    assert by_key["school_profile"].status == "not_started"
    assert by_key["notarization"].status == "not_tracked"
    assert all(s.issuer and s.lead_days_min <= s.lead_days_max for s in steps)
    ru = await DocumentProcessService(factory, k.world.policy).steps(ctx, "ru")
    assert ru[0].title != steps[0].title


async def test_request_notifies_assigned_counselors_only() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    mine = _assign("counselor_full", "student", STUDENT)
    other = dataclasses.replace(
        _assign("counselor_full", "student", OTHER), user_id=new_id()
    )
    for a in (mine, other):
        k.world.store.assignment_rows[a.id] = a
    await k.svc.request(student, _draft())
    assert [n.user_id for n in k.notified] == [STAFF]
    assert k.notified[0].payload["event"] == "requested"


async def test_queue_carries_the_student_name() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    staff = await k.counselor()
    await k.svc.request(student, _draft())
    user = SimpleNamespace(first_name="Ali", last_name="Karimov")

    class _Directory:
        async def get_users(self, ids: Any) -> dict[UUID, Any]:
            return {i: user for i in ids}

    k.svc._identity = _Directory()  # type: ignore[assignment]
    [view] = await k.svc.queue(staff)
    assert view.student_name == "Karimov Ali"


async def test_unassigned_counselor_neither_sees_nor_acts() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    cid = (await k.svc.request(student, _draft())).consultation.id
    loose = await k.world.ctx(STAFF, Role.COUNSELOR)
    assert await k.svc.queue(loose) == []
    elsewhere = await k.counselor(OTHER)
    assert await k.svc.queue(elsewhere) == []
    for step in (
        lambda: k.svc.accept(elsewhere, cid, None, ""),
        lambda: k.svc.propose(elsewhere, cid, LATER, ""),
        lambda: k.svc.decline(elsewhere, cid, "x"),
        lambda: k.svc.cancel(elsewhere, cid),
        lambda: k.svc.complete(elsewhere, cid, "x"),
    ):
        with pytest.raises(AdmissionNotFoundError):
            await step()
    assert k.consults.rows[cid].status == "requested"


async def test_assigned_counselor_queue_read_is_audited() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    cid = (await k.svc.request(student, _draft())).consultation.id
    staff = await k.counselor()
    assert [v.consultation.id for v in await k.svc.queue(staff)] == [cid]
    viewed = [e for e in k.access.events if e.action == VIEWED]
    assert [(e.actor_id, e.student_id, e.object_id) for e in viewed] == [
        (STAFF, STUDENT, cid)
    ]


async def test_counselor_assignment_does_not_answer_mentor_requests() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    cid = (await k.svc.request(student, _draft(with_kind="mentor"))).consultation.id
    k.world.store.assignments[STAFF] = (_assign("counselor_full", "student", STUDENT),)
    both = await k.world.ctx(STAFF, Role.COUNSELOR, Role.MENTOR)
    assert await k.svc.queue(both) == []
    with pytest.raises(AdmissionNotFoundError):
        await k.svc.accept(both, cid, None, "")


async def test_admin_reaches_every_request() -> None:
    k = Kit()
    student = await k.world.ctx(STUDENT, Role.STUDENT)
    cid = (await k.svc.request(student, _draft())).consultation.id
    admin = await k.world.ctx(new_id(), Role.ADMIN)
    assert [v.consultation.id for v in await k.svc.queue(admin)] == [cid]
    accepted = await k.svc.accept(admin, cid, None, "")
    assert accepted.consultation.status == "accepted"
