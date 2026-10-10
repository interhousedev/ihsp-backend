"""SQL read model of the journal grid (STF-9)."""

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.records import JournalOption
from app.modules.academic.infrastructure.classwork.lesson_queries import (
    fetch_lessons,
    group_name_map,
    lesson_select,
)
from app.modules.academic.infrastructure.classwork.sql_helpers import text_array
from app.modules.academic.infrastructure.orm.lesson import Lesson as LessonRow
from app.modules.academic.infrastructure.orm.mark import Mark
from app.modules.academic.infrastructure.orm.result import Result
from app.modules.academic.infrastructure.orm.subject import Subject
from app.modules.academic.infrastructure.school_days import not_on_saturday

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


class SqlJournalReader:
    """Implements JournalReader on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def options(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[JournalOption]:
        """Distinct subject and audience pairs of the teacher's scheduled lessons."""
        stmt = (
            sa.select(
                LessonRow.subject_id,
                Subject.name,
                Subject.short_name,
                LessonRow.audience,
            )
            .distinct()
            .join(Subject, Subject.id == LessonRow.subject_id)
            .where(
                LessonRow.teacher_id == teacher_id,
                LessonRow.status == "scheduled",
                LessonRow.date >= start,
                LessonRow.date <= end,
                not_on_saturday(LessonRow.date),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        groups = await group_name_map(self.session, rows)
        found: dict[tuple[UUID, tuple[str, ...]], JournalOption] = {}
        for row in rows:
            audience = tuple(sorted(row.audience))
            names = {str(k): str(v) for k, v in (row.name or {}).items() if v}
            found[(row.subject_id, audience)] = JournalOption(
                subject_id=row.subject_id,
                subject_names=names,
                subject_short=row.short_name,
                audience=audience,
                groups={
                    gid: groups[gid]
                    for gid in audience_keys.group_ids(audience)
                    if gid in groups
                },
            )
        return list(found.values())

    async def lessons(
        self,
        subject_id: UUID,
        audience: Sequence[str],
        start: dt.date,
        end: dt.date,
    ) -> list[Lesson]:
        """Scheduled lessons of a subject whose audience is exactly these keys."""
        same = sa.and_(
            LessonRow.audience.op("@>", is_comparison=True)(text_array(audience)),
            LessonRow.audience.op("<@", is_comparison=True)(text_array(audience)),
        )
        stmt = (
            lesson_select()
            .where(
                LessonRow.subject_id == subject_id,
                LessonRow.status == "scheduled",
                LessonRow.date >= start,
                LessonRow.date <= end,
                same,
            )
            .order_by(LessonRow.date, LessonRow.period, LessonRow.id)
        )
        return await fetch_lessons(self.session, stmt)

    async def marks_by_cell(
        self, lesson_ids: Sequence[UUID]
    ) -> dict[tuple[UUID, UUID], list[int]]:
        """Mark values per (lesson, student)."""
        if not lesson_ids:
            return {}
        stmt = (
            sa.select(Mark.lesson_id, Mark.student_id, Mark.value)
            .where(Mark.lesson_id.in_(list(lesson_ids)), Mark.removed_at.is_(None))
            .order_by(Mark.created_at)
        )
        cells: dict[tuple[UUID, UUID], list[int]] = {}
        for lesson_id, student_id, value in (await self.session.execute(stmt)).all():
            cells.setdefault((lesson_id, student_id), []).append(value)
        return cells

    async def semester_marks(
        self, student_ids: Sequence[UUID], subject_id: UUID, semester: int
    ) -> dict[UUID, float | None]:
        """Semester mark of each student in the subject."""
        if not student_ids:
            return {}
        stmt = sa.select(Result.student_id, Result.value).where(
            Result.student_id.in_(list(student_ids)),
            Result.subject_id == subject_id,
            Result.semester == semester,
        )
        return {
            student_id: None if value is None else float(value)
            for student_id, value in (await self.session.execute(stmt)).all()
        }
