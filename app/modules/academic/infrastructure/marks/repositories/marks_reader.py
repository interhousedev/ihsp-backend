"""SQL read queries behind the student-facing marks views."""

import datetime as dt
from collections.abc import Collection, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.academic.domain.audience import student_keys
from app.modules.academic.domain.marks.attendance_merge import (
    EmisAttendanceReport,
    RosterEntry,
    merge_attendance,
)
from app.modules.academic.domain.marks.read_models import (
    AttendanceCount,
    GroupRoles,
    LessonRow,
    MarkRow,
    ResultRow,
    StudentContext,
    SubjectInfo,
)
from app.modules.academic.infrastructure.marks.sql_helpers import has_uuid, overlaps
from app.modules.academic.infrastructure.orm.emis_attendance import EmisAttendance
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.lesson import Lesson
from app.modules.academic.infrastructure.orm.mark import Mark
from app.modules.academic.infrastructure.orm.result import Result
from app.modules.academic.infrastructure.orm.room import Room
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.infrastructure.orm.subject import Subject
from app.modules.academic.infrastructure.orm.term import Term
from app.modules.academic.infrastructure.school_days import not_on_saturday

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

_LESSON_COLUMNS = (
    Lesson.id,
    Lesson.date,
    Lesson.period,
    Lesson.starts_at,
    Lesson.ends_at,
    Lesson.subject_id,
    Lesson.teacher_id,
    Lesson.room_id,
    Room.slug.label("room_slug"),
    Room.name.label("room_name"),
    Lesson.audience,
    Lesson.status,
    Lesson.is_overridden,
    Lesson.changes,
    Lesson.topic,
    Lesson.homework_text,
    Lesson.attendance_roster,
    Lesson.attendance_absent,
    Lesson.attendance_excused,
    Lesson.attendance_late,
    Lesson.kind,
    Lesson.emis_topic,
)


def _lesson_row(r: Any) -> LessonRow:
    return LessonRow(
        id=r.id,
        date=r.date,
        period=r.period,
        starts_at=r.starts_at,
        ends_at=r.ends_at,
        subject_id=r.subject_id,
        teacher_id=r.teacher_id,
        room_id=r.room_id,
        room_slug=r.room_slug,
        room_name=r.room_name,
        audience=tuple(r.audience or ()),
        status=r.status,
        is_overridden=r.is_overridden,
        changes=r.changes,
        topic=r.topic,
        homework_text=r.homework_text,
        attendance_roster=(
            None if r.attendance_roster is None else tuple(r.attendance_roster)
        ),
        attendance_absent=(
            None if r.attendance_absent is None else tuple(r.attendance_absent)
        ),
        attendance_excused=r.attendance_excused,
        attendance_late=(
            None if r.attendance_late is None else tuple(r.attendance_late)
        ),
        kind=r.kind,
        emis_topic=r.emis_topic,
    )


def _mark_row(r: Any) -> MarkRow:
    return MarkRow(
        subject_id=r.subject_id,
        semester=r.semester,
        type=r.type,
        value=r.value,
        date=r.date,
        ordinal=r.ordinal,
        lesson_id=r.lesson_id,
        created_at=r.created_at,
    )


_MARK_COLUMNS = (
    Mark.subject_id,
    Mark.semester,
    Mark.type,
    Mark.value,
    Mark.date,
    Mark.ordinal,
    Mark.lesson_id,
    Mark.created_at,
)


class SqlMarksReader:
    """Implements MarksReader on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def student_context(self, user_id: UUID) -> StudentContext | None:
        """Return the student with group data, or None."""
        stmt = (
            sa.select(
                Student.user_id,
                Student.group_id,
                Group.name,
                Student.subgroup,
                Group.current_semester,
                Group.subject_ids,
                Student.synced_at,
                Student.backfilled_at,
            )
            .join(Group, Group.id == Student.group_id)
            .where(Student.user_id == user_id)
        )
        r = (await self.session.execute(stmt)).first()
        if r is None:
            return None
        return StudentContext(
            user_id=r.user_id,
            group_id=r.group_id,
            group_name=r.name,
            subgroup=r.subgroup,
            current_semester=r.current_semester,
            curriculum_subject_ids=tuple(r.subject_ids or ()),
            synced_at=r.synced_at,
            backfilled_at=r.backfilled_at,
        )

    async def subjects(self, subject_ids: Collection[UUID]) -> dict[UUID, SubjectInfo]:
        """Return subjects by id."""
        if not subject_ids:
            return {}
        stmt = sa.select(Subject.id, Subject.name, Subject.short_name).where(
            Subject.id.in_(list(subject_ids))
        )
        return {
            r.id: SubjectInfo(id=r.id, name=dict(r.name), short_name=r.short_name)
            for r in (await self.session.execute(stmt)).all()
        }

    async def results(self, student_id: UUID, semester: int | None) -> list[ResultRow]:
        """Return result rows of one semester or of all semesters."""
        stmt = sa.select(
            Result.semester,
            Result.subject_id,
            Result.value,
            Result.lesson_avg,
            Result.midterm_avg,
            Result.final_avg,
            Result.emis_rating,
            Result.marks_count,
        ).where(Result.student_id == student_id)
        if semester is not None:
            stmt = stmt.where(Result.semester == semester)
        stmt = stmt.order_by(Result.semester)
        return [
            ResultRow(
                semester=r.semester,
                subject_id=r.subject_id,
                value=r.value,
                lesson_avg=r.lesson_avg,
                midterm_avg=r.midterm_avg,
                final_avg=r.final_avg,
                emis_rating=r.emis_rating,
                marks_count=r.marks_count,
            )
            for r in (await self.session.execute(stmt)).all()
        ]

    async def marks(
        self,
        student_id: UUID,
        *,
        semester: int | None = None,
        subject_id: UUID | None = None,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> list[MarkRow]:
        """Return non-removed marks, newest date first."""
        stmt = sa.select(*_MARK_COLUMNS).where(
            Mark.student_id == student_id, Mark.removed_at.is_(None)
        )
        if semester is not None:
            stmt = stmt.where(Mark.semester == semester)
        if subject_id is not None:
            stmt = stmt.where(Mark.subject_id == subject_id)
        if start is not None:
            stmt = stmt.where(Mark.date >= start)
        if end is not None:
            stmt = stmt.where(Mark.date <= end)
        stmt = stmt.order_by(Mark.date.desc(), Mark.type, Mark.ordinal)
        return [_mark_row(r) for r in (await self.session.execute(stmt)).all()]

    async def new_marks(
        self, student_id: UUID, since: dt.datetime | None, limit: int
    ) -> list[MarkRow]:
        """Return non-removed marks first seen after a moment, newest first."""
        stmt = sa.select(*_MARK_COLUMNS).where(
            Mark.student_id == student_id, Mark.removed_at.is_(None)
        )
        if since is not None:
            stmt = stmt.where(Mark.created_at > since)
        stmt = stmt.order_by(Mark.created_at.desc(), Mark.date.desc()).limit(limit)
        return [_mark_row(r) for r in (await self.session.execute(stmt)).all()]

    def _lesson_select(self, ctx: StudentContext) -> sa.Select[Any]:
        """Select the lessons of the student's audience with their rooms."""
        keys = student_keys(ctx.group_id, ctx.subgroup)
        return (
            sa.select(*_LESSON_COLUMNS)
            .select_from(Lesson)
            .outerjoin(Room, Room.id == Lesson.room_id)
            .where(overlaps(Lesson.audience, keys), not_on_saturday(Lesson.date))
        )

    async def lessons(
        self,
        ctx: StudentContext,
        *,
        subject_id: UUID | None = None,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> list[LessonRow]:
        """Return the student's lessons by audience, ordered by date and period."""
        stmt = self._lesson_select(ctx)
        if subject_id is not None:
            stmt = stmt.where(Lesson.subject_id == subject_id)
        if start is not None:
            stmt = stmt.where(Lesson.date >= start)
        if end is not None:
            stmt = stmt.where(Lesson.date <= end)
        stmt = stmt.order_by(Lesson.date, Lesson.period)
        return [_lesson_row(r) for r in (await self.session.execute(stmt)).all()]

    async def next_lessons(
        self, ctx: StudentContext, subject_ids: Collection[UUID], after: dt.datetime
    ) -> dict[UUID, LessonRow]:
        """Return the next scheduled lesson per subject that ends after a moment."""
        if not subject_ids:
            return {}
        stmt = (
            self._lesson_select(ctx)
            .where(
                Lesson.subject_id.in_(list(subject_ids)),
                Lesson.status == "scheduled",
                Lesson.ends_at > after,
            )
            .distinct(Lesson.subject_id)
            .order_by(Lesson.subject_id, Lesson.starts_at)
        )
        rows = (await self.session.execute(stmt)).all()
        return {r.subject_id: _lesson_row(r) for r in rows}

    async def attendance_counts(
        self,
        student_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
        *,
        semester: int | None = None,
    ) -> dict[UUID, AttendanceCount]:
        """Return absences and counted lessons per subject.

        With a semester, EMIS attendance of that semester overrides the rosters.
        """
        stmt = sa.select(
            Lesson.subject_id,
            Lesson.date,
            has_uuid(Lesson.attendance_absent, student_id),
            has_uuid(Lesson.attendance_late, student_id),
        ).where(has_uuid(Lesson.attendance_roster, student_id))
        if start is not None:
            stmt = stmt.where(Lesson.date >= start)
        if end is not None:
            stmt = stmt.where(Lesson.date <= end)
        roster: dict[UUID, list[RosterEntry]] = {}
        for row in (await self.session.execute(stmt)).all():
            roster.setdefault(row[0], []).append(
                RosterEntry(row[1], bool(row[2]), bool(row[3]))
            )
        emis = (
            {} if semester is None else await self.emis_attendance(student_id, semester)
        )
        return {
            sid: merge_attendance(
                roster.get(sid, []),
                None if sid not in emis else emis[sid].within(start, end),
            )
            for sid in roster.keys() | {s for s, r in emis.items() if not r.empty}
        }

    async def emis_attendance(
        self, student_id: UUID, semester: int
    ) -> dict[UUID, EmisAttendanceReport]:
        """Return what EMIS reported per subject for one semester."""
        stmt = sa.select(EmisAttendance).where(
            EmisAttendance.student_id == student_id,
            EmisAttendance.semester == semester,
        )
        return {
            row.subject_id: EmisAttendanceReport(
                None if row.absent_dates is None else frozenset(row.absent_dates),
                row.absence_total,
            )
            for row in (await self.session.scalars(stmt)).all()
        }

    async def teacher_ids(
        self,
        ctx: StudentContext,
        subject_ids: Collection[UUID],
        start: dt.date | None,
        end: dt.date | None,
    ) -> dict[UUID, list[UUID]]:
        """Return the teachers who taught each subject to the student's audience."""
        if not subject_ids:
            return {}
        stmt = (
            sa.select(Lesson.subject_id, Lesson.teacher_id)
            .where(
                overlaps(Lesson.audience, student_keys(ctx.group_id, ctx.subgroup)),
                Lesson.subject_id.in_(list(subject_ids)),
                Lesson.teacher_id.is_not(None),
                Lesson.status == "scheduled",
            )
            .distinct()
            .order_by(Lesson.subject_id, Lesson.teacher_id)
        )
        if start is not None:
            stmt = stmt.where(Lesson.date >= start)
        if end is not None:
            stmt = stmt.where(Lesson.date <= end)
        found: dict[UUID, list[UUID]] = {}
        for row in (await self.session.execute(stmt)).all():
            found.setdefault(row.subject_id, []).append(row.teacher_id)
        return found

    async def group_names(self, group_ids: Collection[UUID]) -> dict[UUID, str]:
        """Return group names by id."""
        if not group_ids:
            return {}
        stmt = sa.select(Group.id, Group.name).where(Group.id.in_(list(group_ids)))
        return {r.id: r.name for r in (await self.session.execute(stmt)).all()}

    async def terms(self) -> list[tuple[dt.date, dt.date]]:
        """Return the dates of every term."""
        stmt = sa.select(Term.starts_on, Term.ends_on).order_by(Term.starts_on)
        return [
            (r.starts_on, r.ends_on) for r in (await self.session.execute(stmt)).all()
        ]

    async def gpa_values(
        self, user_ids: Sequence[UUID], semester: int | None
    ) -> dict[UUID, Decimal | None]:
        """Return the GPA of each student (their current semester if None)."""
        if not user_ids:
            return {}
        wanted = Group.current_semester if semester is None else sa.literal(semester)
        stmt = (
            sa.select(Student.user_id, Result.value)
            .join(Group, Group.id == Student.group_id)
            .join(
                Result,
                sa.and_(
                    Result.student_id == Student.user_id,
                    Result.subject_id.is_(None),
                    Result.semester == wanted,
                ),
            )
            .where(Student.user_id.in_(list(user_ids)))
        )
        return {r.user_id: r.value for r in (await self.session.execute(stmt)).all()}

    async def group_roles(self, group_id: UUID) -> GroupRoles | None:
        """Return the group's curator, head student and active students."""
        group = (
            await self.session.execute(
                sa.select(
                    Group.id,
                    Group.name,
                    Group.current_semester,
                    Group.curator_id,
                    Group.head_student_id,
                ).where(Group.id == group_id)
            )
        ).first()
        if group is None:
            return None
        ids = (
            await self.session.execute(
                sa.select(Student.user_id).where(
                    Student.group_id == group_id, Student.status == "active"
                )
            )
        ).scalars()
        return GroupRoles(
            id=group.id,
            name=group.name,
            current_semester=group.current_semester,
            curator_id=group.curator_id,
            head_student_id=group.head_student_id,
            student_ids=tuple(ids),
        )
