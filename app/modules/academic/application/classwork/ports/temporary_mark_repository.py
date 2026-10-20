"""Port: rows of the temporary gradebook (TMP-1)."""

import datetime as dt
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.temporary_mark import TemporaryMark


class TemporaryMarkRepository(Protocol):
    """Rows of ``academic.temporary_marks``, unique per lesson and student."""

    async def for_lesson(self, lesson_id: UUID) -> list[TemporaryMark]:
        """The lesson's temporary marks, oldest first."""
        ...

    async def upsert(
        self,
        *,
        lesson_id: UUID,
        student_id: UUID,
        subject_id: UUID,
        date: dt.date,
        value: int,
        comment: str | None,
        author_id: UUID,
        at: dt.datetime,
    ) -> TemporaryMark:
        """Create the mark or overwrite its value and comment."""
        ...

    async def delete(self, lesson_id: UUID, student_id: UUID) -> bool:
        """Delete one mark; False when there was none."""
        ...

    async def pending(self, teacher_id: UUID | None) -> list[TemporaryMark]:
        """Marks not yet in EMIS on lessons of the teacher (None: every teacher)."""
        ...

    async def lessons_of(self, marks: Sequence[TemporaryMark]) -> dict[UUID, UUID]:
        """Teacher id of each mark's lesson (lessons without a teacher left out)."""
        ...
