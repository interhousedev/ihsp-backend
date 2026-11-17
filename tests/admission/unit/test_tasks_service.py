"""TaskService: owner CRUD, staff creation, scope 404 / permission 403, filters."""

import datetime as dt
from dataclasses import replace
from typing import Any
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import (
    AdmissionContext,
    ResolveAdmissionActor,
)
from app.modules.admission.application.tasks import TaskService
from app.modules.admission.domain.access import Assignment, StaffRole
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidAnswerError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.tasks import Task, TaskStep
from app.modules.admission.ports.consent import STAFF_VIEW
from app.modules.admission.ports.repositories import OptIns
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

STUDENT, OTHER, STAFF, GROUP = new_id(), new_id(), new_id(), new_id()
TODAY = NOW.astimezone(dt.timezone(dt.timedelta(hours=5))).date()


class MemTasks:
    """In-memory TaskRepository."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Task] = {}

    async def list_for(self, student_id: UUID) -> list[Task]:
        return [t for t in self.rows.values() if t.student_id == student_id]

    async def get(self, task_id: UUID) -> Task | None:
        return self.rows.get(task_id)

    async def add(self, task: Task) -> Task:
        self.rows[task.id] = replace(task, created_at=NOW, updated_at=NOW)
        return self.rows[task.id]

    async def save(self, task: Task, *, expected_lock: int) -> Task:
        if self.rows[task.id].lock_version != expected_lock:
            raise AdmissionConflictError()
        self.rows[task.id] = replace(task, lock_version=expected_lock + 1)
        return self.rows[task.id]

    async def delete(self, task_id: UUID) -> None:
        self.rows.pop(task_id, None)


class TasksUow(FakeUow):
    def __init__(self, store: FakeStore, tasks: MemTasks) -> None:
        super().__init__(store)
        self.tasks = tasks


def _staff(kind: str, *perms: Permission) -> Assignment:
    return Assignment(
        id=new_id(),
        user_id=STAFF,
        role=StaffRole(
            id=new_id(),
            kind=kind,  # type: ignore[arg-type]
            name="Tasks",
            name_i18n={},
            permissions=frozenset(perms),
            is_builtin=False,
        ),
        scope_kind="all" if kind == "counselor" else "student",
        scope_ref=None if kind == "counselor" else STUDENT,
        starts_at=NOW - dt.timedelta(days=1),
        expires_at=None,
        granted_by=None,
    )


class World:
    def __init__(self) -> None:
        self.store, self.mem = FakeStore(), MemTasks()
        members = FakeMembership(
            [student_ref(STUDENT, GROUP), student_ref(OTHER, new_id())]
        )
        uow = lambda: TasksUow(self.store, self.mem)  # noqa: E731
        consents = FakeConsents(
            {STUDENT: frozenset({STAFF_VIEW}), OTHER: frozenset({STAFF_VIEW})}
        )
        clock = FixedClock(NOW)
        self.policy = AccessPolicy(uow, members, consents, clock, {10, 11})
        self.resolver = ResolveAdmissionActor(uow, members, clock, {10, 11})
        self.svc = TaskService(uow, self.policy, clock)

    async def ctx(self, user: UUID, role: Role) -> AdmissionContext:
        return await self.resolver.execute(Actor(user, frozenset({role})))

    async def staff(self, kind: str, role: Role, *perms: Permission) -> Any:
        self.store.assignments[STAFF] = (_staff(kind, *perms),)
        self.store.opt_ins[STAFF] = OptIns(mentee_opt_in=True, mentor_opt_in=True)
        self.store.opt_ins[STUDENT] = OptIns(mentee_opt_in=True, mentor_opt_in=True)
        return await self.ctx(STAFF, role)


def _draft(student: UUID = STUDENT, **kw: Any) -> Task:
    return Task(id=new_id(), student_id=student, **{"title": "Write essay"} | kw)


async def test_owner_creates_lists_updates_deletes() -> None:
    w = World()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    made = await w.svc.create(ctx, STUDENT, _draft(created_by="mentor"))
    assert made.created_by == "student" and made.creator_id == STUDENT
    assert [t.id for t in await w.svc.list_for(ctx, STUDENT)] == [made.id]
    done = await w.svc.update(ctx, made.id, {"status": "done"}, made.lock_version)
    assert done.status == "done" and done.completed_at == NOW
    await w.svc.delete(ctx, made.id)
    assert await w.svc.list_for(ctx, STUDENT) == []


async def test_stale_lock_conflicts() -> None:
    w = World()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    made = await w.svc.create(ctx, STUDENT, _draft())
    await w.svc.update(ctx, made.id, {"title": "A"}, made.lock_version)
    with pytest.raises(AdmissionConflictError):
        await w.svc.update(ctx, made.id, {"title": "B"}, made.lock_version)


async def test_bad_deadline_is_refused() -> None:
    w = World()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    with pytest.raises(InvalidAnswerError):
        await w.svc.create(ctx, STUDENT, _draft(deadline=dt.date(1901, 1, 1)))
    made = await w.svc.create(ctx, STUDENT, _draft())
    with pytest.raises(InvalidAnswerError):
        await w.svc.update(
            ctx, made.id, {"deadline": dt.date(1901, 1, 1)}, made.lock_version
        )


async def test_toggle_step_keeps_status() -> None:
    w = World()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    step = TaskStep(new_id(), "Outline")
    made = await w.svc.create(ctx, STUDENT, _draft(steps=(step,)))
    after = await w.svc.toggle_step(ctx, made.id, step.id, True)
    assert after.progress == (1, 1) and after.status == "planned"


async def test_other_student_cannot_reach_tasks() -> None:
    w = World()
    owner = await w.ctx(STUDENT, Role.STUDENT)
    made = await w.svc.create(owner, STUDENT, _draft())
    other = await w.ctx(OTHER, Role.STUDENT)
    with pytest.raises((AdmissionNotFoundError, AdmissionForbiddenError)):
        await w.svc.list_for(other, STUDENT)
    with pytest.raises((AdmissionNotFoundError, AdmissionForbiddenError)):
        await w.svc.create(other, STUDENT, _draft())
    with pytest.raises((AdmissionNotFoundError, AdmissionForbiddenError)):
        await w.svc.get(other, made.id)
    with pytest.raises((AdmissionNotFoundError, AdmissionForbiddenError)):
        await w.svc.delete(other, made.id)
    assert made.id in w.mem.rows


async def test_unknown_task_is_not_found() -> None:
    w = World()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    with pytest.raises(AdmissionNotFoundError):
        await w.svc.get(ctx, new_id())


async def test_mentor_with_permission_creates_for_student() -> None:
    w = World()
    mentor = await w.staff(
        "mentor", Role.MENTOR, Permission.DEADLINES_MANAGE, Permission.ACTIVITIES_READ
    )
    made = await w.svc.create(mentor, STUDENT, _draft())
    assert made.created_by == "mentor" and made.creator_id == STAFF
    assert [t.id for t in await w.svc.list_for(mentor, STUDENT)] == [made.id]


async def test_counselor_creation_is_marked_counselor() -> None:
    w = World()
    counselor = await w.staff("counselor", Role.COUNSELOR, Permission.DEADLINES_MANAGE)
    made = await w.svc.create(counselor, STUDENT, _draft())
    assert made.created_by == "counselor"


async def test_staff_without_permission_gets_403_and_out_of_scope_404() -> None:
    w = World()
    reader = await w.staff("mentor", Role.MENTOR, Permission.ACTIVITIES_READ)
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.create(reader, STUDENT, _draft())
    assert await w.svc.list_for(reader, STUDENT) == []
    w.store.assignments[STAFF] = ()
    nobody = await w.ctx(STAFF, Role.MENTOR)
    with pytest.raises(AdmissionNotFoundError):
        await w.svc.list_for(nobody, STUDENT)


async def test_filters_and_overdue_flag() -> None:
    w = World()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    day = dt.timedelta(days=1)
    late = await w.svc.create(
        ctx, STUDENT, _draft(deadline=TODAY - day, priority="high")
    )
    soon = await w.svc.create(ctx, STUDENT, _draft(deadline=TODAY + day))
    far = await w.svc.create(ctx, STUDENT, _draft(deadline=TODAY + 60 * day))
    done = await w.svc.create(ctx, STUDENT, _draft(deadline=TODAY - day))
    await w.svc.update(ctx, done.id, {"status": "done"}, done.lock_version)

    def ids(rows: list[Task]) -> set[UUID]:
        return {t.id for t in rows}

    assert ids(await w.svc.list_for(ctx, STUDENT, horizon="overdue")) == {late.id}
    assert ids(await w.svc.list_for(ctx, STUDENT, priority="high")) == {late.id}
    assert ids(await w.svc.list_for(ctx, STUDENT, status="done")) == {done.id}
    assert far.id not in ids(await w.svc.list_for(ctx, STUDENT, horizon="month"))
    assert ids(await w.svc.list_for(ctx, STUDENT, source="mentor")) == set()
    assert soon.id in ids(await w.svc.list_for(ctx, STUDENT, source="student"))
    assert w.svc.today() == TODAY


async def test_create_many_is_owner_only_and_marked_ai() -> None:
    w = World()
    ctx = await w.ctx(STUDENT, Role.STUDENT)
    out = await w.svc.create_many(ctx, [_draft(), _draft(title="Second")], source="ai")
    assert {t.created_by for t in out} == {"ai"} and len(out) == 2
    mentor = await w.staff("mentor", Role.MENTOR, Permission.DEADLINES_MANAGE)
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.create_many(mentor, [_draft()], source="ai")


async def test_peer_helper_cannot_read_the_task_board() -> None:
    w = World()
    owner = await w.ctx(STUDENT, Role.STUDENT)
    made = await w.svc.create(owner, STUDENT, _draft())
    helper = await w.ctx(OTHER, Role.STUDENT)
    with pytest.raises(AdmissionNotFoundError):
        await w.svc.list_for(helper, STUDENT)
    with pytest.raises(AdmissionNotFoundError):
        await w.svc.get(helper, made.id)
