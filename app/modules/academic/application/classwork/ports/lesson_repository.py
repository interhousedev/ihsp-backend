"""Port: reading and changing one lesson's homework, topic and attendance."""

import datetime as dt
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.lesson import Lesson


class LessonRepository(Protocol):
    """Lesson rows with the optimistic attendance version."""

    async def get(self, lesson_id: UUID) -> Lesson | None:
        """Return the lesson with names resolved, or None."""
        ...

    async def get_many(self, lesson_ids: Sequence[UUID]) -> list[Lesson]:
        """Return the lessons that exist."""
        ...

    async def save_attendance(
        self,
        lesson_id: UUID,
        *,
        base_version: int,
        roster: Sequence[UUID],
        absent: Sequence[UUID],
        source: str,
        by: UUID,
        at: dt.datetime,
    ) -> int | None:
        """Write the list if the version still matches; return the new version."""
        ...

    async def toggle_absent(
        self,
        lesson_id: UUID,
        *,
        student_id: UUID,
        absent: bool,
        base_version: int,
        initial_roster: Sequence[UUID],
        source: str,
        by: UUID,
        at: dt.datetime,
    ) -> int | None:
        """Mark or unmark one student in a single statement; None on a conflict."""
        ...

    async def set_excuse(
        self,
        lesson_id: UUID,
        *,
        student_id: UUID,
        excused: bool,
        comment: str | None,
        by: UUID,
        at: dt.datetime,
    ) -> int | None:
        """Excuse or un-excuse an absence; None if the student is not absent."""
        ...

    async def set_homework(
        self,
        lesson_id: UUID,
        *,
        text: str,
        due_date: dt.date | None,
        due_auto: bool,
        by: UUID,
        at: dt.datetime,
        mark_updated: bool,
    ) -> None:
        """Save the homework; ``mark_updated`` sets the "updated" badge time."""
        ...

    async def clear_homework(self, lesson_id: UUID, at: dt.datetime) -> None:
        """Remove the homework."""
        ...

    async def set_topic(
        self, lesson_id: UUID, topic: str | None, at: dt.datetime
    ) -> None:
        """Set or clear the lesson topic."""
        ...

    async def set_due_date(self, lesson_id: UUID, due_date: dt.date | None) -> None:
        """Change an automatic due date without touching the "updated" badge."""
        ...

    async def next_lesson_date(
        self, *, subject_id: UUID, audience: Sequence[str], after: dt.date
    ) -> dt.date | None:
        """Earliest scheduled lesson of the subject for the audience after a date."""
        ...

    async def auto_homework_before(
        self,
        *,
        subject_id: UUID,
        audience: Sequence[str],
        before: dt.date,
        lookback_days: int,
    ) -> list[Lesson]:
        """Lessons with automatic homework that precede a date in the same series."""
        ...
