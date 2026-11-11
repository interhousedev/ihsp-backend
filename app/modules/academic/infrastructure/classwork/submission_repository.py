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
    HomeworkSubmission.lesson_id,
    HomeworkSubmission.student_id,
    HomeworkSubmission.file_ids,
    HomeworkSubmission.comment,
    HomeworkSubmission.submitted_at,
    HomeworkSubmission.updated_at,
)


def _record(row: Any) -> SubmissionRecord:
    return SubmissionRecord(
        lesson_id=row.lesson_id,
        student_id=row.student_id,
        file_ids=tuple(row.file_ids),
        comment=row.comment,
        submitted_at=row.submitted_at,
        updated_at=row.updated_at,
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

    async def upsert(
        self,
        student_id: UUID,
        lesson_id: UUID,
        file_ids: Sequence[UUID],
        comment: str | None,
        now: dt.datetime,
    ) -> SubmissionRecord:
        """Hand in or replace; a replacement refreshes ``submitted_at``."""
        values = {"file_ids": list(file_ids), "comment": comment, "submitted_at": now}
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
            set_={**values, "updated_at": now},
        ).returning(*_COLUMNS)
        return _record((await self.session.execute(upsert)).one())

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
