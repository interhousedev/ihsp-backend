"""Port: data of the journal grid (STF-9)."""

import datetime as dt
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.records import JournalOption


class JournalReader(Protocol):
    """Subjects, audiences, lessons and marks for a teacher's journal."""

    async def options(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[JournalOption]:
        """Distinct subject and audience pairs of the teacher's scheduled lessons."""
        ...

    async def lessons(
        self,
        subject_id: UUID,
        audience: Sequence[str],
        start: dt.date,
        end: dt.date,
    ) -> list[Lesson]:
        """Scheduled lessons of a subject whose audience is exactly these keys."""
        ...

    async def marks_by_cell(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[tuple[UUID, UUID], list[int]]:
        """Mark values per (lesson, student)."""
        ...

    async def semester_marks(
        self, student_ids: Sequence[UUID], subject_id: UUID, semester: int
    ) -> dict[UUID, float | None]:
        """Semester mark of each student in the subject."""
        ...
