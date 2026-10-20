"""SQL reads for the curator absence digest."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.infrastructure.classwork.lesson_queries import (
    fetch_lessons,
    lesson_select,
)
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.lesson import Lesson as LessonRow

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

PLATFORM_SOURCES = ("bot", "staff", "admin")


class SqlAbsenceDigestReader:
    """Implements AbsenceDigestReader on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def last_lesson_end(self, day: dt.date) -> dt.datetime | None:
        """Latest ``ends_at`` among the day's scheduled lessons."""
        stmt = sa.select(sa.func.max(LessonRow.ends_at)).where(
            LessonRow.date == day, LessonRow.status == "scheduled"
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def lessons_with_absences(self, day: dt.date) -> list[Lesson]:
        """Lessons of the day taken on the platform with at least one absent student."""
        stmt = (
            lesson_select()
            .where(
                LessonRow.date == day,
                LessonRow.status == "scheduled",
                LessonRow.attendance_source.in_(PLATFORM_SOURCES),
                sa.func.coalesce(sa.func.cardinality(LessonRow.attendance_absent), 0)
                > 0,
            )
            .order_by(LessonRow.period, LessonRow.id)
        )
        return await fetch_lessons(self.session, stmt)

    async def group_curators(
        self, group_ids: Sequence[UUID]
    ) -> dict[UUID, UUID | None]:
        """Curator user id of each group (None when it has none)."""
        if not group_ids:
            return {}
        stmt = sa.select(Group.id, Group.curator_id).where(
            Group.id.in_(list(group_ids))
        )
        return dict((await self.session.execute(stmt)).tuples().all())
