"""SQL repository of current results (subject rows and semester GPA rows)."""

from typing import Any
from uuid import UUID

from app.modules.academic.domain.marks.records import ResultSnapshot
from app.modules.academic.infrastructure.orm.result import Result
from app.shared.ids import new_id

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


def _same_row(student_id: UUID, semester: int, subject_id: UUID | None) -> Any:
    """Return the WHERE clause that picks one result row."""
    subject = (
        Result.subject_id.is_(None)
        if subject_id is None
        else Result.subject_id == subject_id
    )
    return sa.and_(
        Result.student_id == student_id, Result.semester == semester, subject
    )


class SqlResultsRepository:
    """Implements ResultsRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def get(
        self, student_id: UUID, semester: int, subject_id: UUID | None
    ) -> ResultSnapshot | None:
        """Return a subject result, or the GPA row for subject_id None."""
        stmt = sa.select(
            Result.value,
            Result.lesson_avg,
            Result.midterm_avg,
            Result.final_avg,
            Result.emis_rating,
            Result.marks_count,
            Result.emis_hash,
        ).where(_same_row(student_id, semester, subject_id))
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None
        return ResultSnapshot(
            value=row.value,
            lesson_avg=row.lesson_avg,
            midterm_avg=row.midterm_avg,
            final_avg=row.final_avg,
            emis_rating=row.emis_rating,
            marks_count=row.marks_count,
            emis_hash=row.emis_hash,
        )

    async def save(
        self,
        student_id: UUID,
        semester: int,
        subject_id: UUID | None,
        snapshot: ResultSnapshot,
    ) -> None:
        """Insert or update a result row (callers hold the student's lock)."""
        values = {
            "value": snapshot.value,
            "lesson_avg": snapshot.lesson_avg,
            "midterm_avg": snapshot.midterm_avg,
            "final_avg": snapshot.final_avg,
            "emis_rating": snapshot.emis_rating,
            "marks_count": snapshot.marks_count,
            "emis_hash": snapshot.emis_hash,
        }
        updated = await self.session.execute(
            sa.update(Result)
            .where(_same_row(student_id, semester, subject_id))
            .values(**values)
        )
        if updated.rowcount == 0:  # type: ignore[attr-defined]
            await self.session.execute(
                sa.insert(Result).values(
                    id=new_id(),
                    student_id=student_id,
                    semester=semester,
                    subject_id=subject_id,
                    **values,
                )
            )
