"""SQL repository for lessons: homework, topic and attendance (ACA-9..11)."""

import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.domain.classwork.audience_match import expand_for_overlap
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.infrastructure.classwork.lesson_queries import (
    fetch_lessons,
    lesson_select,
)
from app.modules.academic.infrastructure.classwork.sql_helpers import overlaps
from app.modules.academic.infrastructure.orm.lesson import Lesson as LessonRow
from app.modules.academic.infrastructure.school_days import not_on_saturday

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

_UUIDS = sa.ARRAY(sa.Uuid)
_TEXTS = sa.ARRAY(sa.Text)

# Every attendance write is one statement guarded by the version, so two editors
# (bot, web, journal) never silently overwrite each other (ACA-11).
_SAVE_ATTENDANCE = sa.text("""
    UPDATE academic.lessons SET
      attendance_roster = :roster,
      attendance_absent = :absent,
      attendance_late = :late,
      attendance_excused = (
        SELECT NULLIF(COALESCE(jsonb_object_agg(e.key, e.value), '{}'::jsonb),
                      '{}'::jsonb)
        FROM jsonb_each(COALESCE(academic.lessons.attendance_excused, '{}'::jsonb)) e
        WHERE e.key = ANY(:absent_text)
      ),
      attendance_version = attendance_version + 1,
      attendance_by = :by,
      attendance_at = :at,
      attendance_source = :source,
      updated_at = :at
    WHERE id = :id AND attendance_version = :base
    RETURNING attendance_version
    """).bindparams(
    sa.bindparam("roster", type_=_UUIDS),
    sa.bindparam("absent", type_=_UUIDS),
    sa.bindparam("late", type_=_UUIDS),
    sa.bindparam("absent_text", type_=_TEXTS),
    sa.bindparam("by", type_=sa.Uuid),
    sa.bindparam("at", type_=sa.DateTime(timezone=True)),
    sa.bindparam("source", type_=sa.String),
    sa.bindparam("id", type_=sa.Uuid),
    sa.bindparam("base", type_=sa.Integer),
)

_TOGGLE = sa.text("""
    UPDATE academic.lessons SET
      attendance_roster = CASE
        WHEN attendance_roster IS NULL THEN :initial_roster
        WHEN :sid = ANY(attendance_roster) THEN attendance_roster
        ELSE array_append(attendance_roster, :sid)
      END,
      attendance_absent = CASE WHEN :absent
        THEN array_append(
               array_remove(COALESCE(attendance_absent, '{}'::uuid[]), :sid), :sid)
        ELSE array_remove(COALESCE(attendance_absent, '{}'::uuid[]), :sid)
      END,
      attendance_late = CASE WHEN :late
        THEN array_append(
               array_remove(COALESCE(attendance_late, '{}'::uuid[]), :sid), :sid)
        ELSE array_remove(COALESCE(attendance_late, '{}'::uuid[]), :sid)
      END,
      attendance_excused = CASE WHEN :absent THEN attendance_excused
        ELSE NULLIF(attendance_excused - :sid_text, '{}'::jsonb)
      END,
      attendance_version = attendance_version + 1,
      attendance_by = :by,
      attendance_at = :at,
      attendance_source = :source,
      updated_at = :at
    WHERE id = :id AND attendance_version = :base
    RETURNING attendance_version
    """).bindparams(
    sa.bindparam("initial_roster", type_=_UUIDS),
    sa.bindparam("sid", type_=sa.Uuid),
    sa.bindparam("sid_text", type_=sa.String),
    sa.bindparam("absent", type_=sa.Boolean),
    sa.bindparam("late", type_=sa.Boolean),
    sa.bindparam("by", type_=sa.Uuid),
    sa.bindparam("at", type_=sa.DateTime(timezone=True)),
    sa.bindparam("source", type_=sa.String),
    sa.bindparam("id", type_=sa.Uuid),
    sa.bindparam("base", type_=sa.Integer),
)

_SET_EXCUSE = sa.text("""
    UPDATE academic.lessons SET
      attendance_excused = CASE WHEN :excused THEN
        COALESCE(attendance_excused, '{}'::jsonb) || jsonb_build_object(
          CAST(:sid_text AS text),
          jsonb_build_object(
            'by', CAST(:by_text AS text),
            'at', CAST(:at_text AS text),
            'comment', CAST(:comment AS text)))
        ELSE NULLIF(COALESCE(attendance_excused, '{}'::jsonb) - :sid_text,
                    '{}'::jsonb)
      END,
      attendance_version = attendance_version + 1,
      updated_at = :at
    WHERE id = :id AND (NOT :excused OR attendance_absent @> ARRAY[:sid])
    RETURNING attendance_version
    """).bindparams(
    sa.bindparam("excused", type_=sa.Boolean),
    sa.bindparam("sid", type_=sa.Uuid),
    sa.bindparam("sid_text", type_=sa.String),
    sa.bindparam("by_text", type_=sa.String),
    sa.bindparam("at_text", type_=sa.String),
    sa.bindparam("comment", type_=sa.String),
    sa.bindparam("at", type_=sa.DateTime(timezone=True)),
    sa.bindparam("id", type_=sa.Uuid),
)


class SqlLessonRepository:
    """Implements LessonRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def get(self, lesson_id: UUID) -> Lesson | None:
        """Return the lesson with names resolved, or None."""
        found = await self.get_many([lesson_id])
        return found[0] if found else None

    async def get_many(self, lesson_ids: Sequence[UUID]) -> list[Lesson]:
        """Return the lessons that exist."""
        if not lesson_ids:
            return []
        stmt = lesson_select().where(LessonRow.id.in_(list(lesson_ids)))
        return await fetch_lessons(self.session, stmt)

    async def save_attendance(
        self,
        lesson_id: UUID,
        *,
        base_version: int,
        roster: Sequence[UUID],
        absent: Sequence[UUID],
        late: Sequence[UUID] = (),
        source: str,
        by: UUID,
        at: dt.datetime,
    ) -> int | None:
        """Write the list if the version still matches; return the new version."""
        result = await self.session.execute(
            _SAVE_ATTENDANCE,
            {
                "roster": list(roster),
                "absent": list(absent),
                "late": list(late),
                "absent_text": [str(user_id) for user_id in absent],
                "by": by,
                "at": at,
                "source": source,
                "id": lesson_id,
                "base": base_version,
            },
        )
        return result.scalar_one_or_none()

    async def toggle_absent(
        self,
        lesson_id: UUID,
        *,
        student_id: UUID,
        absent: bool,
        late: bool = False,
        base_version: int,
        initial_roster: Sequence[UUID],
        source: str,
        by: UUID,
        at: dt.datetime,
    ) -> int | None:
        """Mark or unmark one student in a single statement; None on a conflict."""
        result = await self.session.execute(
            _TOGGLE,
            {
                "initial_roster": list(initial_roster),
                "sid": student_id,
                "sid_text": str(student_id),
                "absent": absent,
                "late": late,
                "by": by,
                "at": at,
                "source": source,
                "id": lesson_id,
                "base": base_version,
            },
        )
        return result.scalar_one_or_none()

    async def set_excuse(
        self,
        lesson_id: UUID,
        *,
        student_id: UUID,
        excused: bool,
        comment: str | None,
        by: UUID,
        at: dt.datetime,
    ) -> int | None:
        """Excuse or un-excuse an absence; None if the student is not absent."""
        result = await self.session.execute(
            _SET_EXCUSE,
            {
                "excused": excused,
                "sid": student_id,
                "sid_text": str(student_id),
                "by_text": str(by),
                "at_text": at.isoformat(),
                "comment": comment,
                "at": at,
                "id": lesson_id,
            },
        )
        return result.scalar_one_or_none()

    async def set_homework(
        self,
        lesson_id: UUID,
        *,
        text: str,
        due_date: dt.date | None,
        due_auto: bool,
        by: UUID,
        at: dt.datetime,
        mark_updated: bool,
    ) -> None:
        """Save the homework; ``mark_updated`` sets the "updated" badge time."""
        values: dict[str, Any] = {
            "homework_text": text,
            "homework_due_date": due_date,
            "homework_due_auto": due_auto,
            "homework_by": by,
            "homework_at": at,
            "updated_at": at,
        }
        if mark_updated:
            values["homework_updated_at"] = at
        await self.session.execute(
            sa.update(LessonRow).where(LessonRow.id == lesson_id).values(**values)
        )

    async def clear_homework(self, lesson_id: UUID, at: dt.datetime) -> None:
        """Remove the homework."""
        await self.session.execute(
            sa.update(LessonRow)
            .where(LessonRow.id == lesson_id)
            .values(
                homework_text=None,
                homework_due_date=None,
                homework_due_auto=True,
                homework_by=None,
                homework_at=None,
                homework_updated_at=None,
                updated_at=at,
            )
        )

    async def set_topic(
        self, lesson_id: UUID, topic: str | None, at: dt.datetime
    ) -> None:
        """Set or clear the lesson topic."""
        await self.session.execute(
            sa.update(LessonRow)
            .where(LessonRow.id == lesson_id)
            .values(topic=topic, updated_at=at)
        )

    async def set_due_date(self, lesson_id: UUID, due_date: dt.date | None) -> None:
        """Change an automatic due date without touching the "updated" badge."""
        await self.session.execute(
            sa.update(LessonRow)
            .where(LessonRow.id == lesson_id)
            .values(homework_due_date=due_date)
        )

    async def next_lesson_date(
        self, *, subject_id: UUID, audience: Sequence[str], after: dt.date
    ) -> dt.date | None:
        """Earliest scheduled lesson of the subject for the audience after a date."""
        stmt = sa.select(sa.func.min(LessonRow.date)).where(
            LessonRow.subject_id == subject_id,
            LessonRow.status == "scheduled",
            LessonRow.date > after,
            not_on_saturday(LessonRow.date),
            overlaps(LessonRow.audience, expand_for_overlap(audience)),
        )
        found: dt.date | None = (await self.session.execute(stmt)).scalar_one()
        return found

    async def auto_homework_before(
        self,
        *,
        subject_id: UUID,
        audience: Sequence[str],
        before: dt.date,
        lookback_days: int,
    ) -> list[Lesson]:
        """Lessons with automatic homework that precede a date in the same series."""
        stmt = lesson_select().where(
            LessonRow.subject_id == subject_id,
            LessonRow.status == "scheduled",
            LessonRow.homework_text.is_not(None),
            LessonRow.homework_due_auto.is_(True),
            LessonRow.date < before,
            LessonRow.date >= before - dt.timedelta(days=lookback_days),
            overlaps(LessonRow.audience, expand_for_overlap(audience)),
        )
        return await fetch_lessons(self.session, stmt)
