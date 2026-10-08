"""Port: marks, results and terms read by Today, lesson pages and curators."""

import datetime as dt
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.records import MarkRecord, TermRecord


class ResultsReader(Protocol):
    """Read access to ``academic.marks``, ``academic.results`` and terms."""

    async def new_marks(
        self, student_id: UUID, since: dt.datetime | None, limit: int
    ) -> list[MarkRecord]:
        """Marks first seen after a moment, newest first."""
        ...

    async def lesson_marks(self, student_id: UUID, lesson_id: UUID) -> list[MarkRecord]:
        """Marks matched to a lesson."""
        ...

    async def gpas(
        self, student_ids: Sequence[UUID], semester: int
    ) -> dict[UUID, float | None]:
        """Semester GPA per student."""
        ...

    async def current_term(self, today: dt.date) -> TermRecord | None:
        """The term containing the date, else the next one, else the last one."""
        ...

    async def term(self, term_id: UUID) -> TermRecord | None:
        """Return a term by id."""
        ...
