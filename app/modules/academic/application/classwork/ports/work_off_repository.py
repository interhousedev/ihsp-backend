"""Ports: work-off templates and work-off tasks (WO-1, WO-3)."""

import datetime as dt
from collections.abc import Collection, Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.work_off import (
    ResolvedWorkOff,
    WorkOff,
    WorkOffStatus,
    WorkOffTemplate,
)


class WorkOffTemplateRepository(Protocol):
    """Rows of ``academic.work_off_templates``."""

    async def list_for_teacher(self, teacher_id: UUID) -> list[WorkOffTemplate]:
        """The teacher's templates, oldest first."""
        ...

    async def get(self, template_id: UUID) -> WorkOffTemplate | None:
        """Return the template or None."""
        ...

    async def get_many(
        self, template_ids: Sequence[UUID], teacher_id: UUID
    ) -> list[WorkOffTemplate]:
        """The templates among these ids that belong to the teacher."""
        ...

    async def add(self, template: WorkOffTemplate) -> None:
        """Insert a template."""
        ...

    async def update(
        self, template_id: UUID, *, text: str, is_default: bool, at: dt.datetime
    ) -> WorkOffTemplate:
        """Change text and default flag; return the row."""
        ...

    async def clear_defaults(
        self, template_ids: Collection[UUID], at: dt.datetime
    ) -> None:
        """Drop the default flag from these templates."""
        ...

    async def delete(self, template_id: UUID) -> None:
        """Delete a template (work-offs keep their text)."""
        ...


class WorkOffRepository(Protocol):
    """Rows of ``academic.work_offs``, unique per lesson and student."""

    async def get(self, work_off_id: UUID) -> WorkOff | None:
        """Return the work-off or None."""
        ...

    async def for_lesson(self, lesson_id: UUID) -> list[WorkOff]:
        """The lesson's work-offs, oldest first."""
        ...

    async def for_lessons(self, lesson_ids: Sequence[UUID]) -> list[WorkOff]:
        """Work-offs of several lessons."""
        ...

    async def upsert(
        self,
        *,
        lesson_id: UUID,
        student_id: UUID,
        assigned_by: UUID,
        resolved: ResolvedWorkOff,
        at: dt.datetime,
    ) -> WorkOff:
        """Create the work-off or replace its task (status goes back to assigned)."""
        ...

    async def update(
        self,
        work_off_id: UUID,
        *,
        text: str,
        due_date: dt.date | None,
        status: WorkOffStatus,
        done_at: dt.datetime | None,
        at: dt.datetime,
    ) -> WorkOff:
        """Overwrite the editable fields; return the row."""
        ...

    async def delete(self, work_off_id: UUID) -> None:
        """Delete one work-off."""
        ...

    async def delete_for_students(
        self, lesson_id: UUID, student_ids: Collection[UUID]
    ) -> None:
        """Delete the lesson's work-offs of these students."""
        ...

    async def delete_unless_absent(
        self, lesson_id: UUID, absent: Collection[UUID]
    ) -> list[UUID]:
        """Delete the lesson's work-offs of students not in ``absent``; return them."""
        ...
