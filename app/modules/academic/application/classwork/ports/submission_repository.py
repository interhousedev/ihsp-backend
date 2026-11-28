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

    async def for_lessons(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[SubmissionRecord]]:
        """Submissions of several lessons, grouped by lesson."""
        ...

    async def upsert(
        self,
        student_id: UUID,
        lesson_id: UUID,
        file_ids: Sequence[UUID],
        text: str | None,
        comment: str | None,
        now: dt.datetime,
    ) -> SubmissionRecord:
        """Hand in or replace.

        A replacement refreshes ``submitted_at`` and puts the review back to
        ``pending``, keeping the teacher's last comment as ``previous_comment``.
        """
        ...

    async def get_by_id(self, submission_id: UUID) -> SubmissionRecord | None:
        """Return the submission or None."""
        ...

    async def set_review(
        self,
        submission_id: UUID,
        *,
        status: str,
        grade: int | None,
        teacher_comment: str | None,
        reviewer_id: UUID,
        now: dt.datetime,
        temporary_mark_id: UUID | None = None,
    ) -> SubmissionRecord:
        """Write a grade or a return, with the temporary mark the grade made."""
        ...

    async def clear_review(self, submission_id: UUID) -> SubmissionRecord:
        """Back to ``pending`` with no grade and no teacher comment."""
        ...

    async def mark_notified(self, submission_id: UUID, now: dt.datetime) -> None:
        """Remember when the teacher was last told about this submission."""
        ...

    async def delete(self, student_id: UUID, lesson_id: UUID) -> bool:
        """Withdraw; True when there was a submission."""
        ...
