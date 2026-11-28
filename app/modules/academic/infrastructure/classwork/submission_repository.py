"""SQL repository for homework submissions."""

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.domain.classwork.records import SubmissionRecord
from app.modules.academic.infrastructure.orm.homework_submission import (
    HomeworkSubmission,
)
from app.shared.ids import new_id

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    HomeworkSubmission.id,
    HomeworkSubmission.lesson_id,
    HomeworkSubmission.student_id,
    HomeworkSubmission.file_ids,
    HomeworkSubmission.comment,
    HomeworkSubmission.submitted_at,
    HomeworkSubmission.updated_at,
    HomeworkSubmission.text,
    HomeworkSubmission.review_status,
    HomeworkSubmission.grade,
    HomeworkSubmission.teacher_comment,
    HomeworkSubmission.previous_comment,
    HomeworkSubmission.reviewed_by,
    HomeworkSubmission.reviewed_at,
    HomeworkSubmission.notified_at,
    HomeworkSubmission.temporary_mark_id,
)


def _record(row: Any) -> SubmissionRecord:
    return SubmissionRecord(
        id=row.id,
        lesson_id=row.lesson_id,
        student_id=row.student_id,
        file_ids=tuple(row.file_ids),
        comment=row.comment,
        submitted_at=row.submitted_at,
        updated_at=row.updated_at,
        text=row.text,
        review_status=row.review_status,
        grade=row.grade,
        teacher_comment=row.teacher_comment,
        previous_comment=row.previous_comment,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        notified_at=row.notified_at,
        temporary_mark_id=row.temporary_mark_id,
    )


class SqlSubmissionRepository:
    """Implements SubmissionRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def get(self, student_id: UUID, lesson_id: UUID) -> SubmissionRecord | None:
        """Return the submission or None."""
        stmt = sa.select(*_COLUMNS).where(
            HomeworkSubmission.student_id == student_id,
            HomeworkSubmission.lesson_id == lesson_id,
        )
        row = (await self.session.execute(stmt)).first()
        return None if row is None else _record(row)

    async def for_lesson(self, lesson_id: UUID) -> list[SubmissionRecord]:
        """Every submission of a lesson."""
        stmt = sa.select(*_COLUMNS).where(HomeworkSubmission.lesson_id == lesson_id)
        return [_record(row) for row in (await self.session.execute(stmt)).all()]

    async def for_lessons(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[UUID, list[SubmissionRecord]]:
        """Submissions of several lessons, grouped by lesson."""
        grouped: dict[UUID, list[SubmissionRecord]] = {}
        if not lesson_ids:
            return grouped
        stmt = sa.select(*_COLUMNS).where(
            HomeworkSubmission.lesson_id.in_(list(lesson_ids))
        )
        for row in (await self.session.execute(stmt)).all():
            grouped.setdefault(row.lesson_id, []).append(_record(row))
        return grouped

    async def upsert(
        self,
        student_id: UUID,
        lesson_id: UUID,
        file_ids: Sequence[UUID],
        text: str | None,
        comment: str | None,
        now: dt.datetime,
    ) -> SubmissionRecord:
        """Hand in or replace; a replacement reopens the review."""
        values = {
            "file_ids": list(file_ids),
            "text": text,
            "comment": comment,
            "submitted_at": now,
        }
        stmt = pg_insert(HomeworkSubmission).values(
            id=new_id(),
            student_id=student_id,
            lesson_id=lesson_id,
            created_at=now,
            updated_at=now,
            **values,
        )
        upsert = stmt.on_conflict_do_update(
            index_elements=[
                HomeworkSubmission.lesson_id,
                HomeworkSubmission.student_id,
            ],
            set_={
                **values,
                "updated_at": now,
                "previous_comment": sa.func.coalesce(
                    HomeworkSubmission.teacher_comment,
                    HomeworkSubmission.previous_comment,
                ),
                "review_status": "pending",
                "grade": None,
                "teacher_comment": None,
                "reviewed_by": None,
                "reviewed_at": None,
            },
        ).returning(*_COLUMNS)
        return _record((await self.session.execute(upsert)).one())

    async def get_by_id(self, submission_id: UUID) -> SubmissionRecord | None:
        """Return the submission or None."""
        stmt = sa.select(*_COLUMNS).where(HomeworkSubmission.id == submission_id)
        row = (await self.session.execute(stmt)).first()
        return None if row is None else _record(row)

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
        stmt = (
            sa.update(HomeworkSubmission)
            .where(HomeworkSubmission.id == submission_id)
            .values(
                review_status=status,
                grade=grade,
                teacher_comment=teacher_comment,
                reviewed_by=reviewer_id,
                reviewed_at=now,
                updated_at=now,
                temporary_mark_id=temporary_mark_id,
            )
            .returning(*_COLUMNS)
        )
        return _record((await self.session.execute(stmt)).one())

    async def clear_review(self, submission_id: UUID) -> SubmissionRecord:
        """Back to ``pending`` with no grade and no teacher comment."""
        stmt = (
            sa.update(HomeworkSubmission)
            .where(HomeworkSubmission.id == submission_id)
            .values(
                review_status="pending",
                grade=None,
                teacher_comment=None,
                reviewed_by=None,
                reviewed_at=None,
                temporary_mark_id=None,
            )
            .returning(*_COLUMNS)
        )
        return _record((await self.session.execute(stmt)).one())

    async def mark_notified(self, submission_id: UUID, now: dt.datetime) -> None:
        """Remember when the teacher was last told about this submission."""
        await self.session.execute(
            sa.update(HomeworkSubmission)
            .where(HomeworkSubmission.id == submission_id)
            .values(notified_at=now)
        )

    async def delete(self, student_id: UUID, lesson_id: UUID) -> bool:
        """Withdraw; True when there was a submission."""
        stmt = (
            sa.delete(HomeworkSubmission)
            .where(
                HomeworkSubmission.student_id == student_id,
                HomeworkSubmission.lesson_id == lesson_id,
            )
            .returning(HomeworkSubmission.id)
        )
        return (await self.session.execute(stmt)).first() is not None
