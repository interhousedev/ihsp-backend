"""Port: a student's personal tick and note on a lesson's homework."""

import datetime as dt
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.records import TodoRecord


class TodoRepository(Protocol):
    """Rows of ``academic.homework_todos``, unique per student and lesson."""

    async def get(self, student_id: UUID, lesson_id: UUID) -> TodoRecord | None:
        """Return the to-do row or None."""
        ...

    async def upsert_done(
        self,
        student_id: UUID,
        lesson_id: UUID,
        done_at: dt.datetime | None,
        now: dt.datetime,
    ) -> TodoRecord:
        """Tick or untick; creates the row on first use."""
        ...

    async def upsert_note(
        self, student_id: UUID, lesson_id: UUID, note: str | None, now: dt.datetime
    ) -> TodoRecord:
        """Save or clear the note; creates the row on first use."""
        ...
