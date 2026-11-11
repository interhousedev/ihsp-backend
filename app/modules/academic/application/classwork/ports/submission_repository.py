"""Port: the files a student handed in for a lesson's homework."""

import datetime as dt
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.records import SubmissionRecord


class SubmissionRepository(Protocol):
    """Rows of ``academic.homework_submissions``, unique per lesson and student."""

    async def get(self, student_id: UUID, lesson_id: UUID) -> SubmissionRecord | None:
        """Return the submission or None."""
        ...

    async def for_lesson(self, lesson_id: UUID) -> list[SubmissionRecord]:
        """Every submission of a lesson."""
        ...

    async def upsert(
        self,
        student_id: UUID,
        lesson_id: UUID,
        file_ids: Sequence[UUID],
        comment: str | None,
        now: dt.datetime,
    ) -> SubmissionRecord:
        """Hand in or replace; a replacement refreshes ``submitted_at``."""
        ...

    async def delete(self, student_id: UUID, lesson_id: UUID) -> bool:
        """Withdraw; True when there was a submission."""
        ...
