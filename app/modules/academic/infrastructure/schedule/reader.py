"""SQL implementation of the schedule read port."""

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.application.schedule.ports.reader import (
    LessonFilters,
    LessonPage,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.lesson_view import LessonView
from app.modules.academic.infrastructure.orm import Group as GroupRow
from app.modules.academic.infrastructure.orm import Lesson as LessonRow
from app.modules.academic.infrastructure.orm import Room as RoomRow
from app.modules.academic.infrastructure.orm import Student as StudentRow
from app.modules.academic.infrastructure.orm import Subject as SubjectRow
from app.modules.academic.infrastructure.schedule.array_ops import overlaps
from app.modules.academic.infrastructure.schedule.lesson_views import (
    build_views,
    lesson_select,
)
from app.modules.academic.infrastructure.schedule.like import ESCAPE, like_pattern
from app.modules.academic.infrastructure.schedule.projection import projected_views
from app.shared.contracts.academic import RoomRef, StudentRef

from sqlalchemy import ColumnElement, exists, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

CONTROL_KINDS = ("midterm", "final")


class SqlScheduleReader:
    """Reads lessons, rooms and students with short read-only sessions."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Store the session factory."""
        self.sessionmaker = sessionmaker

    # - - - Students and rooms - - -

    async def student_ref(self, user_id: UUID) -> StudentRef | None:
        """Return the student with the group name."""
        stmt = (
            select(StudentRow, GroupRow.name)
            .join(GroupRow, GroupRow.id == StudentRow.group_id)
            .where(StudentRow.user_id == user_id)
        )
        async with self.sessionmaker() as session:
            found = (await session.execute(stmt)).first()
        if found is None:
            return None
        row, group_name = found
        return StudentRef(
            user_id=row.user_id,
            group_id=row.group_id,
            group_name=group_name,
            subgroup=row.subgroup,
            status="left" if row.status == "left" else "active",
            synced_at=row.synced_at,
        )

    async def room_by_slug(self, slug: str) -> RoomRef | None:
        """Return the room with the slug."""
        async with self.sessionmaker() as session:
            row = (
                await session.scalars(select(RoomRow).where(RoomRow.slug == slug))
            ).first()
        if row is None:
            return None
        return RoomRef(
            id=row.id,
            slug=row.slug,
            name=row.name,
            pin=row.pin,
            status="archived" if row.status == "archived" else "active",
        )

    async def group_user_ids(
        self, group_ids: Sequence[UUID], semesters: Sequence[int]
    ) -> list[UUID]:
        """Return user ids of active students of the groups and semesters.

        Empty group_ids with semesters means every group in those semesters; with
        neither filter nobody is returned.
        """
        if not group_ids and not semesters:
            return []
        stmt = (
            select(StudentRow.user_id)
            .join(GroupRow, GroupRow.id == StudentRow.group_id)
            .where(StudentRow.status == "active")
        )
        if group_ids:
            stmt = stmt.where(StudentRow.group_id.in_(list(group_ids)))
        if semesters:
            stmt = stmt.where(GroupRow.current_semester.in_(list(semesters)))
        async with self.sessionmaker() as session:
            return list(await session.scalars(stmt))

    async def curated_group_ids(self, teacher_id: UUID) -> list[UUID]:
        """Return the active groups the teacher curates."""
        stmt = select(GroupRow.id).where(
            GroupRow.curator_id == teacher_id, GroupRow.status == "active"
        )
        async with self.sessionmaker() as session:
            return list(await session.scalars(stmt))

    async def _keys(self, session: AsyncSession, user_id: UUID) -> list[str] | None:
        row = await session.get(StudentRow, user_id)
        return audience_keys.student_keys(row.group_id, row.subgroup) if row else None

    # - - - Lessons - - -

    async def lesson_view(self, lesson_id: UUID, locale: str) -> LessonView | None:
        """Return one lesson."""
        stmt = lesson_select().where(LessonRow.id == lesson_id)
        async with self.sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
            views = await build_views(session, rows, locale)
        return views[0] if views else None

    async def _query(
        self,
        conditions: Sequence[ColumnElement[bool]],
        locale: str,
        limit: int | None = None,
    ) -> list[LessonView]:
        stmt = (
            lesson_select()
            .where(*conditions)
            .order_by(LessonRow.date, LessonRow.starts_at, LessonRow.id)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        async with self.sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
            return await build_views(session, rows, locale)

    async def lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Return the student's lessons (any status) between two dates."""
        async with self.sessionmaker() as session:
            keys = await self._keys(session, user_id)
        if keys is None:
            return []
        return await self._query(
            [overlaps(LessonRow.audience, keys), LessonRow.date.between(start, end)],
            locale,
        )

    async def lessons_for_teacher(
        self, teacher_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Return the teacher's lessons (any status) between two dates."""
        return await self._query(
            [LessonRow.teacher_id == teacher_id, LessonRow.date.between(start, end)],
            locale,
        )

    async def control_lessons(
        self,
        group_ids: Sequence[UUID],
        start: dt.date,
        end: dt.date,
        locale: str,
    ) -> list[LessonView]:
        """Return the groups' scheduled midterm and final lessons between two dates."""
        keys = [
            key
            for group_id in group_ids
            for key in audience_keys.student_keys(group_id, None)
        ]
        if not keys:
            return []
        return await self._query(
            [
                LessonRow.kind.in_(CONTROL_KINDS),
                LessonRow.status == "scheduled",
                LessonRow.date.between(start, end),
                overlaps(LessonRow.audience, keys),
            ],
            locale,
        )

    async def projected_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[LessonView]:
        """Return generated lessons plus lessons projected from entries."""
        async with self.sessionmaker() as session:
            keys = await self._keys(session, user_id)
            if keys is None:
                return []
            projected = await projected_views(session, keys, start, end, locale)
        generated = await self.lessons_for_student(user_id, start, end, locale)
        merged = [*generated, *projected]
        merged.sort(key=lambda view: (view.ref.starts_at, str(view.ref.id)))
        return merged

    async def is_in_audience(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Return True if the active student attends the lesson."""
        async with self.sessionmaker() as session:
            student = await session.get(StudentRow, user_id)
            if student is None or student.status != "active":
                return False
            keys = audience_keys.student_keys(student.group_id, student.subgroup)
            stmt = select(
                exists().where(
                    LessonRow.id == lesson_id, overlaps(LessonRow.audience, keys)
                )
            )
            return bool((await session.execute(stmt)).scalar_one())

    async def is_lesson_teacher(self, user_id: UUID, lesson_id: UUID) -> bool:
        """Return True if the user is the lesson's teacher."""
        stmt = select(
            exists().where(LessonRow.id == lesson_id, LessonRow.teacher_id == user_id)
        )
        async with self.sessionmaker() as session:
            return bool((await session.execute(stmt)).scalar_one())

    async def head_student_ids(self, lesson_id: UUID) -> list[UUID]:
        """Return head students of the groups in the lesson's audience."""
        async with self.sessionmaker() as session:
            lesson = await session.get(LessonRow, lesson_id)
            if lesson is None:
                return []
            groups = list(audience_keys.group_ids(lesson.audience or []))
            if not groups:
                return []
            stmt = select(GroupRow.head_student_id).where(
                GroupRow.id.in_(groups), GroupRow.head_student_id.is_not(None)
            )
            return [uid for uid in await session.scalars(stmt) if uid is not None]

    async def room_day(
        self, room_id: UUID, day: dt.date, locale: str
    ) -> list[LessonView]:
        """Return the room's lessons on a day ordered by period."""
        stmt = (
            lesson_select()
            .where(LessonRow.room_id == room_id, LessonRow.date == day)
            .order_by(LessonRow.period, LessonRow.starts_at, LessonRow.id)
        )
        async with self.sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
            return await build_views(session, rows, locale)

    async def search_lessons(
        self, user_id: UUID, query: str, limit: int, locale: str
    ) -> list[LessonView]:
        """Search the user's lessons by subject, topic or homework."""
        async with self.sessionmaker() as session:
            keys = await self._keys(session, user_id)
        mine: list[ColumnElement[bool]] = [LessonRow.teacher_id == user_id]
        if keys is not None:
            mine.append(overlaps(LessonRow.audience, keys))
        pattern = like_pattern(query.strip())
        text_match = or_(
            LessonRow.topic.ilike(pattern, escape=ESCAPE),
            LessonRow.homework_text.ilike(pattern, escape=ESCAPE),
            SubjectRow.name["uz"].astext.ilike(pattern, escape=ESCAPE),
            SubjectRow.name["ru"].astext.ilike(pattern, escape=ESCAPE),
            SubjectRow.name["en"].astext.ilike(pattern, escape=ESCAPE),
            SubjectRow.short_name.ilike(pattern, escape=ESCAPE),
        )
        stmt = (
            lesson_select()
            .where(or_(*mine), text_match)
            .order_by(LessonRow.date.desc(), LessonRow.period, LessonRow.id)
            .limit(limit)
        )
        async with self.sessionmaker() as session:
            rows = (await session.execute(stmt)).all()
            return await build_views(session, rows, locale)

    async def list_lessons(
        self,
        filters: LessonFilters,
        *,
        cursor: dict[str, Any] | None,
        limit: int,
        locale: str,
    ) -> LessonPage:
        """Return a page of lessons ordered by date, period and id."""
        stmt = lesson_select().where(*_filter_conditions(filters))
        if cursor is not None:
            after = (
                dt.date.fromisoformat(cursor["d"]),
                int(cursor["p"]),
                UUID(cursor["i"]),
            )
            stmt = stmt.where(
                tuple_(LessonRow.date, LessonRow.period, LessonRow.id)
                > tuple_(*(literal(value) for value in after))
            )
        stmt = stmt.order_by(LessonRow.date, LessonRow.period, LessonRow.id)
        async with self.sessionmaker() as session:
            rows = (await session.execute(stmt.limit(limit + 1))).all()
            views = await build_views(session, rows[:limit], locale)
        more = len(rows) > limit
        next_cursor = None
        if more and views:
            last = views[-1].ref
            next_cursor = {
                "d": last.date.isoformat(),
                "p": last.period,
                "i": str(last.id),
            }
        return LessonPage(items=views, next_cursor=next_cursor)


def _filter_conditions(filters: LessonFilters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.start is not None:
        conditions.append(LessonRow.date >= filters.start)
    if filters.end is not None:
        conditions.append(LessonRow.date <= filters.end)
    if filters.group_id is not None:
        group = filters.group_id
        conditions.append(
            overlaps(LessonRow.audience, [str(group), f"{group}:1", f"{group}:2"])
        )
    if filters.teacher_id is not None:
        conditions.append(LessonRow.teacher_id == filters.teacher_id)
    if filters.room_id is not None:
        conditions.append(LessonRow.room_id == filters.room_id)
    if filters.status is not None:
        conditions.append(LessonRow.status == filters.status)
    if filters.teacher_needed is not None:
        needed = LessonRow.teacher_id.is_(None)
        conditions.append(needed if filters.teacher_needed else ~needed)
    return conditions
