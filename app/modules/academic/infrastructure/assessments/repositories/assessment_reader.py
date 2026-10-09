"""SQL read queries that assessments need from other academic tables."""

import datetime as dt
from collections.abc import Collection, Sequence
from uuid import UUID

from app.modules.academic.application.assessments.ports.repositories import (
    StudentAudience,
)
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.assessments.periods import TermControls
from app.modules.academic.domain.marks.read_models import SubjectInfo
from app.modules.academic.domain.schedule.term import control_periods_from_json
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.lesson import Lesson
from app.modules.academic.infrastructure.orm.student import Student
from app.modules.academic.infrastructure.orm.subject import Subject
from app.modules.academic.infrastructure.orm.term import Term
from app.modules.academic.infrastructure.orm.timetable_entry import TimetableEntry
from app.modules.academic.infrastructure.schedule.repositories import (
    student_repository,
)

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

TAUGHT_PAST_DAYS = 370
TAUGHT_FUTURE_DAYS = 60


class SqlAssessmentReader:
    """Implements AssessmentReader on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def student(self, user_id: UUID) -> StudentAudience | None:
        """Return the student's group and subgroup, or None."""
        stmt = (
            sa.select(Student.user_id, Student.group_id, Group.name, Student.subgroup)
            .join(Group, Group.id == Student.group_id)
            .where(Student.user_id == user_id)
        )
        r = (await self.session.execute(stmt)).first()
        if r is None:
            return None
        return StudentAudience(r.user_id, r.group_id, r.name, r.subgroup)

    async def head_student_of(self, group_id: UUID) -> UUID | None:
        """Return the head student of a group, or None."""
        stmt = sa.select(Group.head_student_id).where(Group.id == group_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

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

    async def group_names(self, group_ids: Collection[UUID]) -> dict[UUID, str]:
        """Return the names of the groups that exist."""
        if not group_ids:
            return {}
        stmt = sa.select(Group.id, Group.name).where(Group.id.in_(list(group_ids)))
        return {r.id: r.name for r in (await self.session.execute(stmt)).all()}

    async def taught_groups(
        self, teacher_id: UUID, today: dt.date
    ) -> dict[UUID, set[UUID]]:
        """Return the groups a teacher teaches, per subject (timetable and lessons)."""
        entries = sa.select(TimetableEntry.subject_id, TimetableEntry.audience).where(
            TimetableEntry.teacher_id == teacher_id,
            sa.or_(TimetableEntry.valid_to.is_(None), TimetableEntry.valid_to >= today),
        )
        lessons = sa.select(Lesson.subject_id, Lesson.audience).where(
            Lesson.teacher_id == teacher_id,
            Lesson.date >= today - dt.timedelta(days=TAUGHT_PAST_DAYS),
            Lesson.date <= today + dt.timedelta(days=TAUGHT_FUTURE_DAYS),
        )
        taught: dict[UUID, set[UUID]] = {}
        for stmt in (entries, lessons):
            for subject_id, audience in (
                await self.session.execute(stmt.distinct())
            ).all():
                taught.setdefault(subject_id, set()).update(
                    audience_keys.group_ids(audience)
                )
        return taught

    async def lesson_subject(self, lesson_id: UUID) -> UUID | None:
        """Return the subject of a lesson, or None when there is no such lesson."""
        stmt = sa.select(Lesson.subject_id).where(Lesson.id == lesson_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def user_ids_for_audience(self, keys: Sequence[str]) -> list[UUID]:
        """Return the active students who belong to the audience."""
        if not keys:
            return []
        stmt = sa.select(Student.user_id).where(
            Student.status == "active", student_repository.audience_condition(keys)
        )
        return list(await self.session.scalars(stmt))

    async def terms(self) -> list[TermControls]:
        """Return every term with its control weeks, oldest first."""
        stmt = sa.select(
            Term.id, Term.starts_on, Term.ends_on, Term.control_periods
        ).order_by(Term.starts_on)
        return [
            TermControls(
                r.id,
                r.starts_on,
                r.ends_on,
                control_periods_from_json(r.control_periods),
            )
            for r in (await self.session.execute(stmt)).all()
        ]

    async def curriculum(self, group_id: UUID) -> tuple[UUID, ...]:
        """Return the subjects of a group's curriculum."""
        stmt = sa.select(Group.subject_ids).where(Group.id == group_id)
        found = (await self.session.execute(stmt)).scalar_one_or_none()
        return tuple(found or ())

    async def curricula(self) -> dict[UUID, tuple[UUID, ...]]:
        """Return the curriculum subjects of every active group that has any."""
        stmt = sa.select(Group.id, Group.subject_ids).where(
            Group.status == "active", sa.func.cardinality(Group.subject_ids) > 0
        )
        return {
            r.id: tuple(r.subject_ids) for r in (await self.session.execute(stmt)).all()
        }

    async def active_group_ids(self) -> list[UUID]:
        """Return the ids of the active groups (those whose controls are suggested)."""
        stmt = sa.select(Group.id).where(Group.status == "active").order_by(Group.id)
        return list(await self.session.scalars(stmt))
