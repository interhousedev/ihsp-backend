"""SQL read models over lessons: views, to-do lists, absences and reminders."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.records import HomeworkRecord, TodoRecord
from app.modules.academic.infrastructure.classwork.lesson_queries import (
    fetch_lessons,
    group_name_map,
    lesson_select,
    lessons_from_rows,
)
from app.modules.academic.infrastructure.classwork.sql_helpers import (
    has_uuid,
    overlaps,
)
from app.modules.academic.infrastructure.orm.homework_todo import HomeworkTodo
from app.modules.academic.infrastructure.orm.lesson import Lesson as LessonRow
from app.modules.academic.infrastructure.school_days import on_school_day

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


class SqlLessonReader:
    """Implements LessonReader on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def audience_lessons(
        self,
        keys: Sequence[str],
        start: dt.date,
        end: dt.date,
        *,
        subject_id: UUID | None = None,
    ) -> list[Lesson]:
        """Lessons of any status whose audience matches the keys, by date."""
        stmt = lesson_select().where(
            overlaps(LessonRow.audience, keys),
            LessonRow.date >= start,
            LessonRow.date <= end,
        )
        if subject_id is not None:
            stmt = stmt.where(LessonRow.subject_id == subject_id)
        stmt = stmt.order_by(LessonRow.date, LessonRow.period, LessonRow.id)
        return await fetch_lessons(self.session, stmt)

    async def teacher_lessons(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[Lesson]:
        """The teacher's lessons of any status between two dates."""
        stmt = (
            lesson_select()
            .where(
                LessonRow.teacher_id == teacher_id,
                LessonRow.date >= start,
                LessonRow.date <= end,
            )
            .order_by(LessonRow.date, LessonRow.period, LessonRow.id)
        )
        return await fetch_lessons(self.session, stmt)

    async def visible_lesson(
        self, keys: Sequence[str], lesson_id: UUID
    ) -> Lesson | None:
        """The lesson if its audience matches the keys."""
        stmt = lesson_select().where(
            LessonRow.id == lesson_id, overlaps(LessonRow.audience, keys)
        )
        found = await fetch_lessons(self.session, stmt)
        return found[0] if found else None

    async def next_study_day(
        self, keys: Sequence[str], after: dt.date
    ) -> dt.date | None:
        """Earliest date after ``after`` with a scheduled lesson (Monday to Friday)."""
        stmt = sa.select(sa.func.min(LessonRow.date)).where(
            overlaps(LessonRow.audience, keys),
            LessonRow.status == "scheduled",
            LessonRow.date > after,
            on_school_day(LessonRow.date),
        )
        found: dt.date | None = (await self.session.execute(stmt)).scalar_one()
        return found

    async def first_scheduled_on(
        self, keys: Sequence[str], day: dt.date
    ) -> Lesson | None:
        """The first scheduled lesson of a day for the keys."""
        stmt = (
            lesson_select()
            .where(
                overlaps(LessonRow.audience, keys),
                LessonRow.status == "scheduled",
                LessonRow.date == day,
            )
            .order_by(LessonRow.starts_at, LessonRow.period)
            .limit(1)
        )
        found = await fetch_lessons(self.session, stmt)
        return found[0] if found else None

    async def homework_records(
        self, student_id: UUID, keys: Sequence[str], since: dt.date
    ) -> list[HomeworkRecord]:
        """Scheduled lessons with homework from a date on, with the to-do state."""
        stmt = (
            lesson_select()
            .add_columns(
                HomeworkTodo.done_at.label("todo_done_at"),
                HomeworkTodo.note.label("todo_note"),
                HomeworkTodo.updated_at.label("todo_updated_at"),
                HomeworkTodo.id.label("todo_id"),
            )
            .outerjoin(
                HomeworkTodo,
                sa.and_(
                    HomeworkTodo.lesson_id == LessonRow.id,
                    HomeworkTodo.student_id == student_id,
                ),
            )
            .where(
                overlaps(LessonRow.audience, keys),
                LessonRow.status == "scheduled",
                LessonRow.homework_text.is_not(None),
                LessonRow.date >= since,
            )
            .order_by(LessonRow.date, LessonRow.period)
        )
        rows = (await self.session.execute(stmt)).all()
        lessons = lessons_from_rows(rows, await group_name_map(self.session, rows))
        records: list[HomeworkRecord] = []
        for lesson, row in zip(lessons, rows, strict=True):
            todo = None
            if row.todo_id is not None:
                todo = TodoRecord(
                    student_id=student_id,
                    lesson_id=lesson.id,
                    done_at=row.todo_done_at,
                    note=row.todo_note,
                    updated_at=row.todo_updated_at,
                )
            records.append(HomeworkRecord(lesson=lesson, todo=todo))
        return records

    async def student_absences(
        self, student_id: UUID, start: dt.date, end: dt.date
    ) -> list[tuple[Lesson, bool]]:
        """Lessons the student missed and whether each absence is excused."""
        stmt = (
            lesson_select()
            .where(
                has_uuid(LessonRow.attendance_absent, student_id),
                LessonRow.status == "scheduled",
                LessonRow.date >= start,
                LessonRow.date <= end,
            )
            .order_by(LessonRow.date.desc(), LessonRow.period.desc())
        )
        lessons = await fetch_lessons(self.session, stmt)
        key = str(student_id)
        return [(lesson, key in lesson.excused_ids()) for lesson in lessons]

    async def missing_attendance(
        self,
        teacher_id: UUID | None,
        start: dt.date,
        end: dt.date,
        now: dt.datetime,
    ) -> list[Lesson]:
        """Finished scheduled lessons with a teacher and no submitted attendance."""
        stmt = lesson_select().where(
            LessonRow.status == "scheduled",
            LessonRow.attendance_absent.is_(None),
            LessonRow.ends_at < now,
            LessonRow.date >= start,
            LessonRow.date <= end,
        )
        if teacher_id is None:
            stmt = stmt.where(LessonRow.teacher_id.is_not(None))
        else:
            stmt = stmt.where(LessonRow.teacher_id == teacher_id)
        stmt = stmt.order_by(LessonRow.date, LessonRow.period, LessonRow.id)
        return await fetch_lessons(self.session, stmt)

    async def starting_between(
        self, start: dt.datetime, end: dt.datetime
    ) -> list[Lesson]:
        """Scheduled lessons starting in ``(start, end]``."""
        stmt = lesson_select().where(
            LessonRow.status == "scheduled",
            LessonRow.starts_at > start,
            LessonRow.starts_at <= end,
        )
        return await fetch_lessons(self.session, stmt)

    async def ending_between(
        self, start: dt.datetime, end: dt.datetime
    ) -> list[Lesson]:
        """Scheduled lessons ending in ``(start, end]``."""
        stmt = lesson_select().where(
            LessonRow.status == "scheduled",
            LessonRow.ends_at > start,
            LessonRow.ends_at <= end,
        )
        return await fetch_lessons(self.session, stmt)
