"""Port: the tasks of a student."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.tasks import Task


class TaskRepository(Protocol):
    """Tasks with their steps and links."""

    async def list_for(self, student_id: UUID) -> list[Task]:
        """Return the student's tasks, newest first."""
        ...

    async def get(self, task_id: UUID) -> Task | None:
        """Return one task."""
        ...

    async def add(self, task: Task) -> Task:
        """Insert a task."""
        ...

    async def save(self, task: Task, *, expected_lock: int) -> Task:
        """Update a task; a different stored lock version raises a conflict."""
        ...

    async def delete(self, task_id: UUID) -> None:
        """Delete a task."""
        ...
