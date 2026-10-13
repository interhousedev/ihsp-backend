"""Schemas of a teacher's subject group and of one student's record in it."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.modules.academic.application.teaching.views import TeachingGroupView

from pydantic import BaseModel, ConfigDict


class _Attrs(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RosterStudentResponse(_Attrs):
    """A student of the group (subgroup None: not assigned)."""

    user_id: UUID
    first_name: str
    last_name: str
    subgroup: int | None


class TeachingLessonResponse(_Attrs):
    """A lesson of the subject for the group."""

    id: UUID
    date: dt.date
    period: int
    starts_at: dt.datetime
    ends_at: dt.datetime
    room_name: str | None
    group_names: list[str]
    status: Literal["scheduled", "cancelled"]
    topic: str | None
    homework_text: str | None
    homework_due_date: dt.date | None


class TeachingGroupResponse(_Attrs):
    """A group (or subgroup) the caller teaches a subject: students and lessons.

    `subgroups` lists the subgroups the caller teaches in the group; empty when the
    group is taught undivided. `lessons` cover this week and the next three.
    """

    subject_id: UUID
    subject_name: str
    group_id: UUID
    group_name: str
    subgroup: int | None
    subgroups: list[int]
    students: list[RosterStudentResponse]
    lessons: list[TeachingLessonResponse]

    @classmethod
    def from_view(cls, view: TeachingGroupView) -> "TeachingGroupResponse":
        """The response of a group view."""
        return cls.model_validate(view)


class TeachingMarkResponse(_Attrs):
    """One mark (2 to 5)."""

    semester: int
    type: str
    value: int
    date: dt.date
    lesson_id: UUID | None


class HomeworkEntryResponse(_Attrs):
    """A homework of the subject and what the student did (`done_at`, `note`)."""

    lesson_id: UUID
    date: dt.date
    due_date: dt.date | None
    text: str | None
    done_at: dt.datetime | None
    note: str | None


class AbsentLessonResponse(_Attrs):
    """A lesson of the subject the student missed."""

    lesson_id: UUID
    date: dt.date
    excused: bool


class TeachingStudentResponse(_Attrs):
    """A student's record in the subject: marks of the newest semester and more.

    `average` is the mean of `marks` on the 5-point scale.
    """

    subject_id: UUID
    subject_name: str
    group_id: UUID
    group_name: str
    student: RosterStudentResponse
    semester: int | None
    marks: list[TeachingMarkResponse]
    average: float | None
    semester_mark: float | None
    homework: list[HomeworkEntryResponse]
    absences: int
    lessons_with_attendance: int | None
    absent_lessons: list[AbsentLessonResponse]
