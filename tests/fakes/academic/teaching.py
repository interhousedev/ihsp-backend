"""Fakes of the academic public queries behind the staff Subjects pages."""

import dataclasses
import datetime as dt
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.shared.actor import Role
from app.shared.contracts.academic import (
    LessonRef,
    MarkRef,
    StudentRef,
    SubjectSummary,
)
from app.shared.contracts.identity import UserRef
from app.shared.ids import new_id
from tests.fakes.ai.contracts import FakeIdentity, make_lesson, make_user

TODAY = dt.date(2026, 10, 6)  # a Tuesday: the FixedClock default
GROUP = new_id()
PHYSICS = new_id()


class Schedule:
    """ScheduleQueries: students, a group roster and lessons."""

    def __init__(self) -> None:
        """Start empty."""
        self.students: dict[UUID, StudentRef] = {}
        self.teacher_lessons: dict[UUID, list[LessonRef]] = {}
        self.student_lessons: list[LessonRef] = []

    async def get_student(self, user_id: UUID) -> StudentRef | None:
        """Return the student."""
        return self.students.get(user_id)

    async def group_user_ids(
        self, group_ids: Sequence[UUID], semesters: Sequence[int] = ()
    ) -> list[UUID]:
        """Return the active students of the groups."""
        return [
            s.user_id
            for s in self.students.values()
            if s.group_id in group_ids and s.status == "active"
        ]

    async def lessons_for_teacher(
        self, teacher_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return the teacher's lessons."""
        found = self.teacher_lessons.get(teacher_id, [])
        return [x for x in found if start <= x.date <= end]

    async def lessons_for_student(
        self, user_id: UUID, start: dt.date, end: dt.date
    ) -> list[LessonRef]:
        """Return the student's lessons."""
        return [x for x in self.student_lessons if start <= x.date <= end]


class Marks:
    """MarksQueries: marks and a summary."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: list[MarkRef] = []
        self.summary: list[SubjectSummary] = []

    async def marks(
        self,
        user_id: UUID,
        subject_id: UUID | None,
        start: dt.date | None,
        end: dt.date | None,
    ) -> list[MarkRef]:
        """Return the marks of a subject."""
        return [m for m in self.rows if m.subject_id == subject_id]

    async def subjects_summary(
        self, user_id: UUID, semester: int | None
    ) -> list[SubjectSummary]:
        """Return the summary."""
        return self.summary


class Classwork:
    """ClassworkQueries: homework and absences."""

    def __init__(self) -> None:
        """Start empty."""
        self.homework_items: list[dict[str, Any]] = []
        self.absence_items: list[dict[str, Any]] = []

    async def homework(
        self,
        user_id: UUID,
        start: dt.date | None,
        end: dt.date | None,
        done: bool | None,
    ) -> list[dict[str, Any]]:
        """Return the homework items."""
        return self.homework_items

    async def absences(
        self, user_id: UUID, start: dt.date | None, end: dt.date | None
    ) -> list[dict[str, Any]]:
        """Return the absences."""
        return self.absence_items

    async def work_off_templates(self, teacher_id: UUID) -> list[dict[str, Any]]:
        """Return no templates."""
        return []

    async def my_work_offs(self, student_id: UUID, locale: str) -> list[dict[str, Any]]:
        """Return no work-offs."""
        return []

    async def teacher_open_work_offs(
        self, teacher_id: UUID, locale: str
    ) -> list[dict[str, Any]]:
        """Return no work-offs."""
        return []


def lesson(
    day: dt.date, *keys: str, subject: UUID = PHYSICS, teacher: UUID | None = None
) -> LessonRef:
    """A physics lesson for the audience keys."""
    names = tuple("2TN2" if ":" not in k else "2TN2/" + k[-1] for k in keys)
    return dataclasses.replace(
        make_lesson(subject_id=subject, day=day, homework="Ex. 4"),
        audience=keys,
        group_names=names,
        teacher_id=teacher,
    )


def student_of(
    schedule: Schedule, identity: FakeIdentity, last: str, subgroup: int | None
) -> UserRef:
    """Add an active student of GROUP."""
    user = make_user(Role.STUDENT, first="A", last=last)
    identity.users[user.id] = user
    schedule.students[user.id] = StudentRef(
        user_id=user.id,
        group_id=GROUP,
        group_name="2TN2",
        subgroup=subgroup,
        status="active",
        synced_at=None,
    )
    return user
