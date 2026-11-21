"""Tasks: the student's own board, plus tasks that staff set for the student.

The owner has full control. Staff in scope read with `activities:read` and
create, edit or delete with `deadlines:manage`. A student out of scope is a 404.
"""

import datetime as dt
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.domain.calendar import TASHKENT
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidAnswerError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.tasks import Task, TaskSource
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.clock import Clock

HORIZONS: Final = ("overdue", "week", "month")
"""Deadline windows a list can be narrowed to."""

_EDITABLE: Final = frozenset(
    {
        "title",
        "description",
        "priority",
        "start_date",
        "deadline",
        "list_entry_id",
        "steps",
        "links",
    }
)


def in_horizon(task: Task, horizon: str, today: dt.date) -> bool:
    """Whether the task falls in the window; `overdue` ignores finished tasks."""
    if horizon == "overdue":
        return task.is_overdue(today)
    if task.deadline is None:
        return False
    if horizon == "week":
        monday = today - dt.timedelta(days=today.weekday())
        return monday <= task.deadline <= monday + dt.timedelta(days=6)
    if horizon == "month":
        return (task.deadline.year, task.deadline.month) == (today.year, today.month)
    raise InvalidAnswerError(params={"field": "horizon"})


class TaskService:
    """Reads and writes of a student's tasks."""

    def __init__(
        self, uow_factory: UowFactory, access: AccessPolicy, clock: Clock
    ) -> None:
        """Keep the transaction factory, the access policy and the clock."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock

    def today(self) -> dt.date:
        """Today's date in Tashkent, the day overdue is measured against."""
        return self._clock.now().astimezone(TASHKENT).date()

    async def _no_helper(self, ctx: AdmissionContext, student_id: UUID) -> None:
        """A peer helper is not staff: the task board stays out of their reach."""
        res = await self._access.resolve(ctx, student_id)
        if not res.owner and not res.via:
            raise AdmissionNotFoundError()

    async def list_for(
        self,
        ctx: AdmissionContext,
        student_id: UUID,
        *,
        status: str | None = None,
        priority: str | None = None,
        source: str | None = None,
        horizon: str | None = None,
    ) -> list[Task]:
        """List the student's tasks, narrowed by the filters."""
        await self._no_helper(ctx, student_id)
        await self._access.require(
            ctx, student_id, Permission.ACTIVITIES_READ, object_type="task"
        )
        async with self._uow() as uow:
            rows = await uow.tasks.list_for(student_id)
        today = self.today()
        return [
            t
            for t in rows
            if (status is None or t.status == status)
            and (priority is None or t.priority == priority)
            and (source is None or t.created_by == source)
            and (horizon is None or in_horizon(t, horizon, today))
        ]

    async def get(self, ctx: AdmissionContext, task_id: UUID) -> Task:
        """Return one task the caller may read."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
        if task is None:
            raise AdmissionNotFoundError()
        await self._no_helper(ctx, task.student_id)
        await self._access.require(
            ctx,
            task.student_id,
            Permission.ACTIVITIES_READ,
            object_type="task",
            object_id=task.id,
        )
        return task

    async def _writer(self, ctx: AdmissionContext, student_id: UUID) -> bool:
        """Check the caller may write; return whether they own the board."""
        res = await self._access.require(
            ctx, student_id, Permission.DEADLINES_MANAGE, object_type="task"
        )
        return res.owner

    @staticmethod
    def _source(ctx: AdmissionContext, owner: bool) -> TaskSource:
        if owner:
            return "student"
        return "counselor" if Role.COUNSELOR in ctx.actor.roles else "mentor"

    @staticmethod
    async def _own_entry(uow: Any, student_id: UUID, entry_id: UUID | None) -> None:
        """The linked list entry must belong to the same student."""
        if entry_id is None:
            return
        entry = await uow.shortlist.entry(entry_id)
        if entry is None or entry.student_id != student_id:
            raise InvalidAnswerError(params={"field": "list_entry_id"})

    async def create(
        self, ctx: AdmissionContext, student_id: UUID, draft: Task
    ) -> Task:
        """Create a task for the student; the source follows the caller."""
        owner = await self._writer(ctx, student_id)
        task = replace(
            draft,
            student_id=student_id,
            created_by=self._source(ctx, owner),
            creator_id=ctx.user_id,
            status="planned",
            completed_at=None,
        )
        task.validate()
        async with self._uow() as uow:
            await self._own_entry(uow, student_id, task.list_entry_id)
            saved = await uow.tasks.add(task)
            self._audit(uow, ctx, "task.created", saved)
            await uow.commit()
        return saved

    async def create_many(
        self,
        ctx: AdmissionContext,
        drafts: Sequence[Task],
        *,
        source: TaskSource,
    ) -> list[Task]:
        """Create tasks on the caller's own board (accepted AI suggestions)."""
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(
                params={"permission": Permission.DEADLINES_MANAGE.value}
            )
        tasks = [
            replace(
                d,
                student_id=ctx.user_id,
                created_by=source,
                creator_id=ctx.user_id,
                status="planned",
                completed_at=None,
            )
            for d in drafts
        ]
        for t in tasks:
            t.validate()
        async with self._uow() as uow:
            for t in tasks:
                await self._own_entry(uow, ctx.user_id, t.list_entry_id)
            saved = [await uow.tasks.add(t) for t in tasks]
            for s in saved:
                self._audit(uow, ctx, "task.created", s)
            await uow.commit()
        return saved

    async def _load(self, ctx: AdmissionContext, task_id: UUID) -> Task:
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
        if task is None:
            raise AdmissionNotFoundError()
        await self._writer(ctx, task.student_id)
        return task

    async def update(
        self,
        ctx: AdmissionContext,
        task_id: UUID,
        changes: dict[str, Any],
        lock_version: int,
    ) -> Task:
        """Change fields and the status of a task."""
        task = await self._load(ctx, task_id)
        edited = replace(task, **{k: v for k, v in changes.items() if k in _EDITABLE})
        if "status" in changes and changes["status"] is not None:
            edited.set_status(changes["status"], self._clock.now())
        edited.validate()
        async with self._uow() as uow:
            if edited.list_entry_id != task.list_entry_id:
                await self._own_entry(uow, task.student_id, edited.list_entry_id)
            saved = await uow.tasks.save(edited, expected_lock=lock_version)
            self._audit(uow, ctx, "task.updated", saved)
            await uow.commit()
        return saved

    async def toggle_step(
        self, ctx: AdmissionContext, task_id: UUID, step_id: UUID, done: bool
    ) -> Task:
        """Check or uncheck one step; the task status stays as it is."""
        task = await self._load(ctx, task_id)
        task.toggle_step(step_id, done)
        async with self._uow() as uow:
            saved = await uow.tasks.save(task, expected_lock=task.lock_version)
            await uow.commit()
        return saved

    async def delete(self, ctx: AdmissionContext, task_id: UUID) -> None:
        """Delete a task."""
        task = await self._load(ctx, task_id)
        async with self._uow() as uow:
            await uow.tasks.delete(task.id)
            self._audit(uow, ctx, "task.deleted", task)
            await uow.commit()

    @staticmethod
    def _audit(uow: Any, ctx: AdmissionContext, action: str, task: Task) -> None:
        uow.access.audit(
            AuditEvent(
                action=action,
                actor_id=ctx.user_id,
                student_id=task.student_id,
                object_type="task",
                object_id=task.id,
            )
        )
