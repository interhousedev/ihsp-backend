"""SQL reads behind the overall student rating."""

import datetime as dt
from collections import defaultdict
from uuid import UUID

from app.modules.academic.application.marks.ports.rating import (
    AcademicYear,
    StudentYearFacts,
)
from app.modules.academic.domain.attendance_merge import AbsenceKey
from app.modules.academic.domain.marks.group_standing import current_term
from app.modules.academic.infrastructure.orm.emis_attendance import EmisAttendance
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.lesson import Lesson
from app.modules.academic.infrastructure.orm.mark import Mark
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.infrastructure.orm.term import Term
from app.modules.academic.infrastructure.orm.work_off import WorkOff

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlRatingSource:
    """Implements `RatingSource` with a few aggregate queries per call."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the session factory."""
        self.sessionmaker = sessionmaker

    async def academic_year(self, today: dt.date) -> AcademicYear | None:
        """The year of the current term, spanning all its terms."""
        async with self.sessionmaker() as session:
            rows = (
                await session.execute(
                    sa.select(Term.academic_year, Term.starts_on, Term.ends_on)
                )
            ).all()
        term = current_term(sorted((r.starts_on, r.ends_on) for r in rows), today)
        if term is None:
            return None
        label = next(r.academic_year for r in rows if (r.starts_on, r.ends_on) == term)
        spans = [(r.starts_on, r.ends_on) for r in rows if r.academic_year == label]
        return AcademicYear(
            label=label,
            starts_on=min(s for s, _ in spans),
            ends_on=max(e for _, e in spans),
        )

    async def year_facts(self, start: dt.date, end: dt.date) -> list[StudentYearFacts]:
        """Facts of every active student of an active, visible group."""
        async with self.sessionmaker() as session:
            students = (
                await session.execute(
                    sa.select(Student.user_id, Group.name)
                    .join(Group, Group.id == Student.group_id)
                    .where(
                        Student.status == "active",
                        Group.status == "active",
                        Group.hidden.is_(False),
                    )
                )
            ).all()
            if not students:
                return []
            marks = (
                await session.execute(
                    sa.select(
                        Mark.student_id,
                        sa.func.sum(Mark.value),
                        sa.func.count(),
                    )
                    .where(
                        Mark.removed_at.is_(None),
                        Mark.type == "lesson",
                        Mark.date.between(start, end),
                    )
                    .group_by(Mark.student_id)
                )
            ).all()
            absent = (
                await session.execute(
                    sa.select(
                        sa.func.unnest(Lesson.attendance_absent).label("uid"),
                        Lesson.subject_id,
                        Lesson.date,
                    ).where(
                        Lesson.attendance_absent.is_not(None),
                        Lesson.date.between(start, end),
                    )
                )
            ).all()
            emis = (
                await session.execute(
                    sa.select(
                        EmisAttendance.student_id,
                        EmisAttendance.subject_id,
                        EmisAttendance.absent_dates,
                    ).where(EmisAttendance.absent_dates.is_not(None))
                )
            ).all()
            work_offs = (
                await session.execute(
                    sa.select(WorkOff.student_id, sa.func.count())
                    .join(Lesson, Lesson.id == WorkOff.lesson_id)
                    .where(Lesson.date.between(start, end))
                    .group_by(WorkOff.student_id)
                )
            ).all()
        mark_totals = {r[0]: (int(r[1] or 0), int(r[2] or 0)) for r in marks}
        platform: dict[UUID, list[AbsenceKey]] = defaultdict(list)
        for uid, subject_id, day in absent:
            platform[uid].append((subject_id, day))
        reported: dict[UUID, list[AbsenceKey]] = defaultdict(list)
        for uid, subject_id, dates in emis:
            reported[uid].extend(
                (subject_id, day) for day in dates if start <= day <= end
            )
        work_off_counts = {r[0]: int(r[1]) for r in work_offs}
        return [
            StudentYearFacts(
                student_id=uid,
                group_name=group_name,
                mark_sum=mark_totals.get(uid, (0, 0))[0],
                mark_count=mark_totals.get(uid, (0, 0))[1],
                platform_absences=platform.get(uid, []),
                emis_absences=reported.get(uid, []),
                work_offs=work_off_counts.get(uid, 0),
            )
            for uid, group_name in students
        ]
