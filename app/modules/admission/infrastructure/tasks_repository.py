"""SQLAlchemy repository of the tasks."""

from typing import Any, cast
from uuid import UUID

from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.tasks import (
    Task,
    TaskLink,
    TaskPriority,
    TaskSource,
    TaskStatus,
    TaskStep,
)
from app.modules.admission.infrastructure.orm.tasks import TaskRow

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _link(raw: dict[str, Any]) -> TaskLink:
    return TaskLink(raw["label"], raw["url"], raw.get("kind", "external"))


def _step(raw: dict[str, Any]) -> TaskStep:
    link = raw.get("link")
    return TaskStep(
        id=UUID(raw["id"]),
        title=raw["title"],
        done=bool(raw.get("done")),
        link=_link(link) if link else None,
    )


def _link_json(link: TaskLink) -> dict[str, Any]:
    return {"label": link.label, "url": link.url, "kind": link.kind}


def _step_json(step: TaskStep) -> dict[str, Any]:
    return {
        "id": str(step.id),
        "title": step.title,
        "done": step.done,
        "link": _link_json(step.link) if step.link else None,
    }


def _task(row: TaskRow) -> Task:
    return Task(
        id=row.id,
        student_id=row.student_id,
        title=row.title,
        description=row.description,
        status=cast(TaskStatus, row.status),
        priority=cast(TaskPriority, row.priority),
        start_date=row.start_date,
        deadline=row.deadline,
        created_by=cast(TaskSource, row.created_by),
        creator_id=row.creator_id,
        steps=tuple(_step(s) for s in row.steps or []),
        links=tuple(_link(x) for x in row.links or []),
        completed_at=row.completed_at,
        lock_version=row.lock_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _fill(row: TaskRow, task: Task) -> None:
    row.title = task.title
    row.description = task.description
    row.status = task.status
    row.priority = task.priority
    row.start_date = task.start_date
    row.deadline = task.deadline
    row.created_by = task.created_by
    row.creator_id = task.creator_id
    row.steps = [_step_json(s) for s in task.steps]
    row.links = [_link_json(x) for x in task.links]
    row.completed_at = task.completed_at


class SqlTaskRepository:
    """Tasks stored in `admission.tasks`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self._s = session

    async def list_for(self, student_id: UUID) -> list[Task]:
        """Return the student's tasks, newest first."""
        rows = await self._s.scalars(
            select(TaskRow)
            .where(TaskRow.student_id == student_id)
            .order_by(TaskRow.created_at.desc(), TaskRow.id)
        )
        return [_task(r) for r in rows]

    async def get(self, task_id: UUID) -> Task | None:
        """Return one task."""
        row = await self._s.get(TaskRow, task_id)
        return _task(row) if row else None

    async def add(self, task: Task) -> Task:
        """Insert a task."""
        row = TaskRow(id=task.id, student_id=task.student_id, lock_version=0)
        _fill(row, task)
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _task(row)

    async def save(self, task: Task, *, expected_lock: int) -> Task:
        """Update a task with a compare-and-set on the lock version."""
        row = await self._s.get(TaskRow, task.id, with_for_update=True)
        if row is None:
            raise AdmissionNotFoundError()
        if row.lock_version != expected_lock:
            raise AdmissionConflictError()
        _fill(row, task)
        row.lock_version = expected_lock + 1
        await self._s.flush()
        await self._s.refresh(row)
        return _task(row)

    async def delete(self, task_id: UUID) -> None:
        """Delete a task."""
        row = await self._s.get(TaskRow, task_id)
        if row is not None:
            await self._s.delete(row)
            await self._s.flush()
