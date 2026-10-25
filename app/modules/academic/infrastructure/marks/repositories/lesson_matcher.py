"""SQL lookup of the lesson a mark belongs to (ACA-14)."""

import datetime as dt
from collections.abc import Collection
from uuid import UUID

from app.modules.academic.domain.audience import student_keys
from app.modules.academic.infrastructure.marks.sql_helpers import overlaps
from app.modules.academic.infrastructure.orm.lesson import Lesson

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


class SqlLessonMatcher:
    """Implements LessonMatcher on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def match(
        self,
        *,
        group_id: UUID,
        subgroup: int | None,
        pairs: Collection[tuple[UUID, dt.date]],
    ) -> dict[tuple[UUID, dt.date], UUID]:
        """Return the earliest lesson of the student's audience per (subject, date)."""
        if not pairs:
            return {}
        wanted = set(pairs)
        stmt = (
            sa.select(Lesson.id, Lesson.subject_id, Lesson.date)
            .where(
                Lesson.subject_id.in_({subject for subject, _day in wanted}),
                Lesson.date.in_({day for _subject, day in wanted}),
                Lesson.status == "scheduled",
                overlaps(Lesson.audience, student_keys(group_id, subgroup)),
            )
            .order_by(Lesson.date, Lesson.period, Lesson.starts_at)
        )
        found: dict[tuple[UUID, dt.date], UUID] = {}
        for row in (await self.session.execute(stmt)).all():
            key = (row.subject_id, row.date)
            if key in wanted:
                found.setdefault(key, row.id)
        return found
