"""Adapter: the library's `AcademicDirectory` over the academic schedule services."""

import datetime as dt
import re
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.subject import subject_name
from app.modules.academic.wiring_schedule import ScheduleServices
from app.modules.library.ports.directories import GroupView, SubjectView
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today

LESSON_WINDOW = dt.timedelta(days=60)
GROUP_YEAR = re.compile(r"^\s*(\d)")


class LibraryAcademicAdapter:
    """Subjects, groups and cohorts for the library, read from academic."""

    def __init__(self, schedule: ScheduleServices, clock: Clock) -> None:
        """Store the schedule services and the clock."""
        self.schedule = schedule
        self.clock = clock

    async def subject_names(
        self, subject_ids: Sequence[UUID], locale: str
    ) -> dict[UUID, str]:
        """Names of the existing subjects in the locale (unknown ids are absent)."""
        wanted = set(subject_ids)
        if not wanted:
            return {}
        subjects = await self.schedule.list_subjects.execute(None)
        return {s.id: subject_name(s, locale) for s in subjects if s.id in wanted}

    async def list_subjects(self, locale: str) -> list[SubjectView]:
        """All subjects, sorted by name."""
        subjects = await self.schedule.list_subjects.execute(None)
        views = [SubjectView(id=s.id, name=subject_name(s, locale)) for s in subjects]
        return sorted(views, key=lambda view: view.name.casefold())

    async def student_group_id(self, user_id: UUID) -> UUID | None:
        """The active group of a student, or None."""
        student = await self.schedule.queries.get_student(user_id)
        if student is None or student.status != "active":
            return None
        return student.group_id

    async def student_cohort(self, user_id: UUID) -> str:
        """The year the student joined ("2025"), or an empty string when unknown.

        The first digit of the group name is the year of study (`2TN2` is a second
        year group); the cohort is the start year of the academic year minus that.
        """
        student = await self.schedule.queries.get_student(user_id)
        if student is None:
            return ""
        match = GROUP_YEAR.match(student.group_name)
        year = await self.current_academic_year()
        if match is None or year is None:
            return ""
        return str(int(year[:4]) - (int(match.group(1)) - 1))

    async def teacher_teaches_subject(self, user_id: UUID, subject_id: UUID) -> bool:
        """True when the teacher has lessons of the subject around today."""
        today = local_today(self.clock)
        lessons = await self.schedule.queries.lessons_for_teacher(
            user_id, today - LESSON_WINDOW, today + LESSON_WINDOW
        )
        return any(lesson.subject_id == subject_id for lesson in lessons)

    async def group_user_ids(self, group_ids: Sequence[UUID]) -> list[UUID]:
        """Active students of the groups."""
        if not group_ids:
            return []
        return await self.schedule.queries.group_user_ids(group_ids)

    async def all_groups(self) -> list[GroupView]:
        """Every active group, sorted by name."""
        groups = await self.schedule.list_groups.execute("active")
        views = [GroupView(id=group.id, name=group.name) for group in groups]
        return sorted(views, key=lambda view: view.name.casefold())

    async def teacher_groups(self, user_id: UUID) -> list[GroupView]:
        """Active groups a teacher curates or has lessons with, sorted by name."""
        actor = Actor(user_id=user_id, roles=frozenset({Role.TEACHER}))
        curated = await self.schedule.list_curated_groups.execute(actor)
        today = local_today(self.clock)
        lessons = await self.schedule.queries.lessons_for_teacher(
            user_id, today - LESSON_WINDOW, today + LESSON_WINDOW
        )
        taught = {
            group_id
            for lesson in lessons
            for group_id in audience_keys.group_ids(lesson.audience)
        }
        known = {group.id: group.name for group in curated}
        if taught - known.keys():
            for group in await self.all_groups():
                if group.id in taught:
                    known.setdefault(group.id, group.name)
        views = [GroupView(id=gid, name=name) for gid, name in known.items()]
        return sorted(views, key=lambda view: view.name.casefold())

    async def current_academic_year(self) -> str | None:
        """The academic year of the current term ("2026-2027"), or None."""
        term = await self.schedule.current_term.execute()
        return term.academic_year if term else None
