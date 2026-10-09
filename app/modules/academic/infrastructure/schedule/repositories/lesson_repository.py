"""SQL repository of lessons (schedule columns)."""

import datetime as dt
from collections.abc import Collection
from uuid import UUID

from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.infrastructure.orm import Lesson as LessonRow
from app.modules.academic.infrastructure.orm import Mark as MarkRow
from app.modules.academic.infrastructure.schedule.array_ops import overlaps
from app.modules.academic.infrastructure.schedule.mappers import (
    lesson_apply,
    lesson_new_row,
    lesson_to_entity,
)
from app.shared.base_error import ConflictError

import structlog
from sqlalchemy import ColumnElement, delete, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_KIND_BY_CONSTRAINT = {
    "ex_lessons_teacher_no_overlap": ("teacher", "The teacher is busy at this time."),
    "ex_lessons_room_no_overlap": ("room", "The room is busy at this time."),
}


def has_content_clause() -> ColumnElement[bool]:
    """Return SQL true when homework, attendance, a topic or marks exist."""
    has_marks = exists().where(
        MarkRow.lesson_id == LessonRow.id, MarkRow.removed_at.is_(None)
    )
    return or_(
        LessonRow.homework_text.is_not(None),
        LessonRow.attendance_absent.is_not(None),
        LessonRow.topic.is_not(None),
        has_marks,
    )


def conflict_from_integrity(error: IntegrityError) -> ConflictError:
    """Translate an exclusion violation into the API's conflict error."""
    message = str(error.orig)
    for name, (kind, description) in _KIND_BY_CONSTRAINT.items():
        if name in message:
            conflict = {
                "kind": kind,
                "with_entry_id": None,
                "with_lesson_id": None,
                "description": description,
            }
            return ConflictError(params={"conflicts": [conflict]})
    return ConflictError(support_details=message)


class SqlLessonRepository:
    """Lessons in the academic schema."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to a session."""
        self.session = session

    async def get(self, lesson_id: UUID) -> Lesson | None:
        """Return the lesson or None."""
        stmt = select(LessonRow, has_content_clause()).where(LessonRow.id == lesson_id)
        found = (await self.session.execute(stmt)).first()
        return lesson_to_entity(found[0], has_content=bool(found[1])) if found else None

    async def add(self, lesson: Lesson) -> None:
        """Insert a lesson; a time conflict raises ConflictError."""
        self.session.add(lesson_new_row(lesson))
        try:
            await self.session.flush()
        except IntegrityError as error:
            raise conflict_from_integrity(error) from error

    async def try_add(self, lesson: Lesson) -> bool:
        """Insert unless a constraint blocks it; return whether it was added."""
        try:
            async with self.session.begin_nested():
                self.session.add(lesson_new_row(lesson))
                await self.session.flush()
        except IntegrityError as error:
            logger.warning(
                "lesson_not_added", lesson_id=str(lesson.id), error=str(error.orig)
            )
            return False
        return True

    async def save(self, lesson: Lesson) -> None:
        """Write the schedule columns of a lesson; a time conflict raises."""
        row = await self.session.get(LessonRow, lesson.id)
        if row is None:
            return
        lesson_apply(row, lesson)
        try:
            await self.session.flush()
        except IntegrityError as error:
            raise conflict_from_integrity(error) from error

    async def try_save(self, lesson: Lesson) -> bool:
        """Write unless a constraint blocks it; return whether it was saved."""
        row = await self.session.get(LessonRow, lesson.id)
        if row is None:
            return False
        try:
            async with self.session.begin_nested():
                lesson_apply(row, lesson)
                await self.session.flush()
        except IntegrityError as error:
            logger.warning(
                "lesson_not_saved", lesson_id=str(lesson.id), error=str(error.orig)
            )
            await self.session.refresh(row)
            return False
        return True

    async def delete_many(self, lesson_ids: Collection[UUID]) -> None:
        """Delete lessons."""
        if not lesson_ids:
            return
        await self.session.execute(
            delete(LessonRow).where(LessonRow.id.in_(list(lesson_ids)))
        )

    async def generated_in_range(
        self, term_id: UUID, start: dt.date, end: dt.date
    ) -> list[Lesson]:
        """Return lessons made from entries whose origin date is in the range."""
        stmt = select(LessonRow, has_content_clause()).where(
            LessonRow.term_id == term_id,
            LessonRow.timetable_entry_id.is_not(None),
            LessonRow.origin_date.between(start, end),
        )
        rows = (await self.session.execute(stmt)).all()
        return [lesson_to_entity(row, has_content=bool(flag)) for row, flag in rows]

    async def in_audience(
        self, term_id: UUID, start: dt.date, end: dt.date, keys: Collection[str]
    ) -> list[Lesson]:
        """Return the term's lessons dated start..end whose audience holds a key."""
        if not keys:
            return []
        stmt = (
            select(LessonRow, has_content_clause())
            .where(
                LessonRow.term_id == term_id,
                LessonRow.date.between(start, end),
                overlaps(LessonRow.audience, list(keys)),
            )
            .order_by(LessonRow.date, LessonRow.period, LessonRow.id)
        )
        rows = (await self.session.execute(stmt)).all()
        return [lesson_to_entity(row, has_content=bool(flag)) for row, flag in rows]

    async def with_emis_class_ids(self, class_ids: Collection[int]) -> list[Lesson]:
        """Return the lessons that mirror one of the EMIS classes."""
        if not class_ids:
            return []
        stmt = select(LessonRow, has_content_clause()).where(
            LessonRow.emis_class_id.in_(list(class_ids))
        )
        rows = (await self.session.execute(stmt)).all()
        return [lesson_to_entity(row, has_content=bool(flag)) for row, flag in rows]

    async def find_overlapping(
        self, starts_at: dt.datetime, ends_at: dt.datetime
    ) -> list[Lesson]:
        """Return scheduled lessons whose time intersects the interval."""
        stmt = select(LessonRow).where(
            LessonRow.status == "scheduled",
            LessonRow.starts_at < ends_at,
            LessonRow.ends_at > starts_at,
        )
        return [lesson_to_entity(row) for row in await self.session.scalars(stmt)]

    async def reassign_room(self, source_id: UUID, target_id: UUID) -> int:
        """Move lessons from one room to another; return how many."""
        try:
            result = await self.session.execute(
                update(LessonRow)
                .where(LessonRow.room_id == source_id)
                .values(room_id=target_id)
                .returning(LessonRow.id)
            )
        except IntegrityError as error:
            raise conflict_from_integrity(error) from error
        return len(result.all())

    async def clear_teacher_future(
        self, teacher_id: UUID, now: dt.datetime
    ) -> list[UUID]:
        """Set teacher_id to NULL on lessons not started yet; return their ids."""
        result = await self.session.execute(
            update(LessonRow)
            .where(LessonRow.teacher_id == teacher_id, LessonRow.starts_at > now)
            .values(teacher_id=None)
            .returning(LessonRow.id)
        )
        return [row[0] for row in result.all()]

    async def count_future_in_room(self, room_id: UUID, now: dt.datetime) -> int:
        """Count scheduled lessons in the room that have not started."""
        stmt = select(func.count()).where(
            LessonRow.room_id == room_id,
            LessonRow.status == "scheduled",
            LessonRow.starts_at > now,
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_by_room(self, start: dt.date, end: dt.date) -> dict[UUID, int]:
        """Count scheduled lessons per room between two dates (inclusive)."""
        stmt = (
            select(LessonRow.room_id, func.count())
            .where(
                LessonRow.room_id.is_not(None),
                LessonRow.status == "scheduled",
                LessonRow.date.between(start, end),
            )
            .group_by(LessonRow.room_id)
        )
        return {row[0]: row[1] for row in (await self.session.execute(stmt)).all()}

    async def detach_entry(self, entry_id: UUID, now: dt.datetime) -> list[UUID]:
        """Prepare an entry for deletion (see the port for the rules)."""
        stmt = select(LessonRow, has_content_clause()).where(
            LessonRow.timetable_entry_id == entry_id
        )
        affected: list[UUID] = []
        to_delete: list[LessonRow] = []
        for row, has_content in (await self.session.execute(stmt)).all():
            row.timetable_entry_id = None
            if row.is_overridden or row.starts_at <= now:
                continue
            affected.append(row.id)
            if has_content:
                row.status = "cancelled"
            else:
                to_delete.append(row)
        for row in to_delete:
            await self.session.delete(row)
        await self.session.flush()
        return affected
