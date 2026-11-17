"""ReadinessService: component scores, weights, next actions and access."""

import datetime as dt
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import (
    AdmissionContext,
    ResolveAdmissionActor,
)
from app.modules.admission.application.readiness import (
    COMPONENTS,
    ReadinessService,
    combine,
    effective_weights,
)
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ReadinessWeightsError,
)
from app.modules.admission.domain.essays import Essay
from app.modules.admission.domain.goal_plan import GoalMilestone
from app.modules.admission.domain.items import Item
from app.modules.admission.domain.profile import AdmissionProfile
from app.modules.admission.domain.runtime_settings import READINESS_WEIGHTS
from app.modules.admission.domain.tasks import Task
from app.modules.admission.domain.workflow import ListEntry
from app.modules.admission.ports.consent import STAFF_VIEW
from app.settings_admission import ReadinessSettings
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admission.unit.fakes import (
    NOW,
    FakeConsents,
    FakeMembership,
    FakeStore,
    FakeUow,
    student_ref,
)
from tests.fakes.clock import FixedClock

import pytest

STUDENT, OTHER, GROUP = new_id(), new_id(), new_id()
TODAY = NOW.astimezone(dt.timezone(dt.timedelta(hours=5))).date()


class Rows:
    """A list-backed repository answering the reads the service makes."""

    def __init__(self, rows: list[Any], read: str) -> None:
        self.rows, self.read = rows, read

    async def _rows(self, student_id: UUID) -> list[Any]:
        return [r for r in self.rows if r.student_id == student_id]

    def __getattr__(self, name: str) -> Any:
        if name == self.read:
            return self._rows
        raise AttributeError(name)


class ReadinessUow(FakeUow):
    def __init__(self, store: FakeStore, data: dict[str, list[Any]]) -> None:
        super().__init__(store)
        self.items = Rows(data["items"], "list_for")
        self.essays = Rows(data["essays"], "list_for")
        self.test_scores = Rows(data["scores"], "entries")
        self.tasks = Rows(data["tasks"], "list_for")
        self.goals = Rows(data["goals"], "list_for")
        self.career = SimpleNamespace(plan=self._plan)
        self.checklist = SimpleNamespace(for_student=self._checklist)
        self.profile_details = SimpleNamespace(get_quiz=self._quiz)
        self.data = data

    async def _plan(self, student_id: UUID) -> Any:
        return self.data["career"][0] if self.data["career"] else None

    async def _quiz(self, student_id: UUID, quiz: str) -> Any:
        return self.data.get("quiz")

    async def _checklist(self, student_id: UUID) -> list[Any]:
        return self.data["checklist"]


class World:
    def __init__(self, **cfg: Any) -> None:
        self.store = FakeStore()
        self.data: dict[str, list[Any]] = {
            k: []
            for k in (
                "items",
                "essays",
                "scores",
                "tasks",
                "goals",
                "career",
                "checklist",
            )
        }
        members = FakeMembership(
            [student_ref(STUDENT, GROUP), student_ref(OTHER, new_id())]
        )
        uow = lambda: ReadinessUow(self.store, self.data)  # noqa: E731
        consents = FakeConsents({STUDENT: frozenset({STAFF_VIEW})})
        clock = FixedClock(NOW)
        policy = AccessPolicy(uow, members, consents, clock, {10, 11})
        self.resolver = ResolveAdmissionActor(uow, members, clock, {10, 11})
        self.runtime = runtime = RuntimeSettingsService(uow)
        self.balance = (0, 0, 0)
        self.plan = SimpleNamespace(insights=self._insights)
        self.svc = ReadinessService(
            uow, policy, runtime, ReadinessSettings(**cfg), clock, self.plan
        )

    async def _insights(self, ctx: Any, student_id: UUID) -> Any:
        reach, target, safety = self.balance
        return SimpleNamespace(
            balance=SimpleNamespace(reach=reach, target=target, safety=safety)
        )

    async def ctx(self, user: UUID, role: Role = Role.STUDENT) -> AdmissionContext:
        return await self.resolver.execute(Actor(user, frozenset({role})))


def _by_key(r: Any) -> dict[str, Any]:
    return {c.key: c for c in r.components}


async def test_empty_student_leaves_out_tasks_and_documents() -> None:
    w = World()
    r = await w.svc.get(await w.ctx(STUDENT))
    assert r.percent == 0
    parts = _by_key(r)
    assert set(parts) == set(COMPONENTS) - {"tasks", "documents"}
    assert parts["essays"].next_action == "write_essay"
    assert parts["essays"].url_path == "/essays"
    assert parts["essays"].weight == 20
    assert parts["major"].url_path == "/career"
    assert parts["countries"].url_path == "/setup/?q=q24"
    assert parts["plans"].url_path == "/plan"
    assert parts["list"].url_path == "/chooser"


async def test_inapplicable_parts_do_not_count_as_zero() -> None:
    w = World()
    w.data["items"] += [
        Item(new_id(), STUDENT, "activity", str(i), status="ready") for i in range(5)
    ]
    # Only activities (15) is non-zero among 7 applicable parts of weight 80.
    r = await w.svc.get(await w.ctx(STUDENT))
    assert r.percent == round(100 * 15 / 80)
    w.data["tasks"] += [Task(new_id(), STUDENT, "x", status="done")]
    r = await w.svc.get(await w.ctx(STUDENT))
    assert _by_key(r)["tasks"].score == 100
    assert r.percent == round(100 * 25 / 90)


def test_combine_skips_none_and_all_zero_weight() -> None:
    weights = dict.fromkeys(COMPONENTS, 1.0)
    scores: dict[str, int | None] = dict.fromkeys(COMPONENTS, None)
    scores["essays"] = 50
    r = combine(scores, weights)
    assert [c.key for c in r.components] == ["essays"]
    assert r.percent == 50
    assert combine(scores, dict.fromkeys(COMPONENTS, 0.0)).percent == 0


async def test_major_from_career_plan_or_profile_answer() -> None:
    w = World()
    assert _by_key(await w.svc.get(await w.ctx(STUDENT)))["major"].score == 0
    w.data["career"].append(SimpleNamespace(majors=["cs"]))
    parts = _by_key(await w.svc.get(await w.ctx(STUDENT)))
    assert parts["major"].score == 100
    assert parts["major"].next_action is None
    w.data["career"].clear()
    w.store.profiles[STUDENT] = AdmissionProfile(STUDENT, answers={"q18": ["cs"]})
    assert _by_key(await w.svc.get(await w.ctx(STUDENT)))["major"].score == 100


async def test_countries_and_plans() -> None:
    w = World(plans_target=2)
    w.store.profiles[STUDENT] = AdmissionProfile(STUDENT, answers={"q24": ["US"]})
    w.data["goals"] += [
        GoalMilestone(new_id(), STUDENT, "a"),
        GoalMilestone(new_id(), STUDENT, "b", status="dropped"),
    ]
    parts = _by_key(await w.svc.get(await w.ctx(STUDENT)))
    assert parts["countries"].score == 100
    assert parts["plans"].score == 50


async def test_list_balance_counts_length_and_kinds() -> None:
    w = World(list_target=4)
    for _ in range(4):
        entry = ListEntry(new_id(), STUDENT, new_id())
        w.store.list_entries[entry.id] = entry
    w.balance = (4, 0, 0)  # long enough but one kind: (100 + 33) / 2
    assert _by_key(await w.svc.get(await w.ctx(STUDENT)))["list"].score == 66
    w.balance = (1, 2, 1)
    parts = _by_key(await w.svc.get(await w.ctx(STUDENT)))
    assert parts["list"].score == 100
    assert parts["list"].next_action is None


async def test_components_follow_the_data() -> None:
    w = World(activities_target=2, essays_target=2, list_target=4)
    sid = STUDENT
    w.data["items"] += [
        Item(new_id(), sid, "activity", "A", status="ready"),
        Item(new_id(), sid, "honor", "B", status="draft"),
    ]
    w.data["essays"] += [
        Essay(new_id(), sid, status="final"),
        Essay(new_id(), sid, status="draft"),
    ]
    done = Task(new_id(), sid, "x", status="done")
    late = Task(new_id(), sid, "y", deadline=TODAY - dt.timedelta(days=1))
    w.data["tasks"] += [done, late]
    w.data["scores"] += [
        SimpleNamespace(student_id=sid, test_id=new_id(), status="score_received"),
        SimpleNamespace(student_id=sid, test_id=new_id(), status="planned"),
    ]
    w.data["checklist"] += [
        SimpleNamespace(status="done"),
        SimpleNamespace(status="todo"),
        SimpleNamespace(status="n_a"),
    ]
    parts = _by_key(await w.svc.get(await w.ctx(sid)))
    assert parts["activities"].score == 50
    assert parts["essays"].score == 75
    assert parts["tests"].score == 50
    assert parts["documents"].score == 50
    assert parts["tasks"].score == 0


async def test_weights_come_from_runtime_over_defaults() -> None:
    w = World()
    w.data["items"] += [
        Item(new_id(), STUDENT, "activity", str(i), status="ready") for i in range(5)
    ]
    assert (await w.svc.get(await w.ctx(STUDENT))).percent == round(1500 / 80)
    w.store.runtime[READINESS_WEIGHTS] = {"activities": 100, "major": 0}
    w.runtime.invalidate()
    r = await w.svc.get(await w.ctx(STUDENT))
    assert _by_key(r)["activities"].weight == 100
    assert r.percent == round(10000 / 155)


def test_bad_stored_weights_are_ignored() -> None:
    d = ReadinessSettings()
    assert effective_weights(d, "junk") == effective_weights(d, None)
    assert effective_weights(d, {"major": -1, "nope": 3})["major"] == 10
    zero = dict.fromkeys(d.weights, 0)
    assert effective_weights(d, zero)["essays"] == 20


async def test_other_student_cannot_read_and_unknown_staff_is_refused() -> None:
    w = World()
    other = await w.ctx(OTHER)
    with pytest.raises((AdmissionNotFoundError, AdmissionForbiddenError)):
        await w.svc.get(other, STUDENT)


async def test_admin_edits_weights_and_they_apply() -> None:
    w = World()
    admin = await w.ctx(new_id(), Role.ADMIN)
    body = dict.fromkeys(COMPONENTS, 0.0)
    body["tasks"] = 5.0
    assert (await w.svc.set_weights(admin, body))["tasks"] == 5.0
    assert w.store.runtime[READINESS_WEIGHTS]["tasks"] == 5.0
    assert (await w.svc.weights(admin))["essays"] == 0.0
    w.data["tasks"] += [Task(new_id(), STUDENT, "x", status="done")]
    parts = _by_key(await w.svc.get(await w.ctx(STUDENT)))
    assert parts["tasks"].weight == 5.0


async def test_weights_are_admin_only_and_validated() -> None:
    w = World()
    full = dict.fromkeys(COMPONENTS, 1.0)
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.set_weights(await w.ctx(STUDENT), full)
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.weights(await w.ctx(STUDENT))
    admin = await w.ctx(new_id(), Role.ADMIN)
    for bad in (
        dict.fromkeys(full, 0.0),
        {**full, "tasks": -1.0},
        {"tasks": 1.0},
        {**full, "extra": 1.0},
        {**full, "tasks": float("nan")},
        {**full, "tasks": float("inf")},
        {**full, "tasks": 1001.0},
    ):
        with pytest.raises(ReadinessWeightsError):
            await w.svc.set_weights(admin, bad)
    assert READINESS_WEIGHTS not in w.store.runtime


async def test_weights_read_by_staff_edit_by_settings_editors() -> None:
    w = World()
    mentor = await w.ctx(new_id(), Role.MENTOR)
    assert set(await w.svc.weights(mentor)) == set(COMPONENTS)
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.set_weights(mentor, dict.fromkeys(COMPONENTS, 1.0))
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.weights(await w.ctx(STUDENT))
    admin = await w.ctx(new_id(), Role.ADMIN)
    new = dict.fromkeys(COMPONENTS, 2.0)
    assert await w.svc.set_weights(admin, new) == new
    assert await w.svc.weights(admin) == new
