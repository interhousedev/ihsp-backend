"""SQL repository of the temporary gradebook (TMP-1, TMP-2)."""

import datetime as dt
from collections.abc import Collection, Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.domain.classwork.temporary_mark import TemporaryMark
from app.modules.academic.infrastructure.orm.lesson import Lesson as LessonRow
from app.modules.academic.infrastructure.orm.mark import Mark as MarkRow
from app.modules.academic.infrastructure.orm.temporary_mark import TemporaryMark as Row
from app.shared.ids import new_id

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


def temporary_mark_of(row: Any) -> TemporaryMark:
    """Map an ORM row to the entity."""
    return TemporaryMark(
        id=row.id,
        lesson_id=row.lesson_id,
        student_id=row.student_id,
        subject_id=row.subject_id,
        date=row.date,
        value=row.value,
        comment=row.comment,
        author_id=row.author_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _in_emis() -> sa.Exists:
    """An active EMIS mark exists for the same student, subject and date."""
    return (
        sa.select(MarkRow.id)
        .where(
            MarkRow.student_id == Row.student_id,
            MarkRow.subject_id == Row.subject_id,
            MarkRow.date == Row.date,
            MarkRow.removed_at.is_(None),
        )
        .exists()
    )


class SqlTemporaryMarkRepository:
    """Implements TemporaryMarkRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def for_lesson(self, lesson_id: UUID) -> list[TemporaryMark]:
        """The lesson's temporary marks, oldest first."""
        stmt = (
            sa.select(Row)
            .where(Row.lesson_id == lesson_id)
            .order_by(Row.created_at, Row.id)
        )
        return [temporary_mark_of(r) for r in (await self.session.scalars(stmt))]

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
        values = {"value": value, "comment": comment, "author_id": author_id}
        stmt = pg_insert(Row).values(
            id=new_id(),
            lesson_id=lesson_id,
            student_id=student_id,
            subject_id=subject_id,
            date=date,
            created_at=at,
            updated_at=at,
            **values,
        )
        upsert = stmt.on_conflict_do_update(
            index_elements=[Row.lesson_id, Row.student_id],
            set_={**values, "updated_at": at},
        ).returning(Row)
        return temporary_mark_of((await self.session.scalars(upsert)).one())

    async def delete(self, lesson_id: UUID, student_id: UUID) -> bool:
        """Delete one mark; False when there was none."""
        stmt = (
            sa.delete(Row)
            .where(Row.lesson_id == lesson_id, Row.student_id == student_id)
            .returning(Row.id)
        )
        return (await self.session.execute(stmt)).first() is not None

    async def pending(self, teacher_id: UUID | None) -> list[TemporaryMark]:
        """Marks not yet in EMIS on lessons of the teacher (None: every teacher)."""
        stmt = (
            sa.select(Row)
            .join(LessonRow, LessonRow.id == Row.lesson_id)
            .where(~_in_emis())
            .order_by(Row.date, LessonRow.period, Row.created_at)
        )
        if teacher_id is not None:
            stmt = stmt.where(LessonRow.teacher_id == teacher_id)
        return [temporary_mark_of(r) for r in (await self.session.scalars(stmt))]

    async def lessons_of(self, marks: Sequence[TemporaryMark]) -> dict[UUID, UUID]:
        """Teacher id of each mark's lesson (lessons without a teacher left out)."""
        ids = list({m.lesson_id for m in marks})
        if not ids:
            return {}
        stmt = sa.select(LessonRow.id, LessonRow.teacher_id).where(
            LessonRow.id.in_(ids), LessonRow.teacher_id.is_not(None)
        )
        rows = (await self.session.execute(stmt)).tuples().all()
        return {
            lesson_id: teacher for lesson_id, teacher in rows if teacher is not None
        }


async def delete_in_emis(
    session: AsyncSession,
    student_id: UUID,
    subject_id: UUID,
    dates: Collection[dt.date],
) -> int:
    """Delete the student's temporary marks of the subject on these dates (TMP-2)."""
    if not dates:
        return 0
    stmt = sa.delete(Row).where(
        Row.student_id == student_id,
        Row.subject_id == subject_id,
        Row.date.in_(list(dates)),
    )
    result: Any = await session.execute(stmt)
    return int(result.rowcount or 0)
