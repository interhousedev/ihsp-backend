"""Read models of a teacher's subject group and of one student in it."""

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

from app.shared.contracts.academic import LessonRef, MarkRef


@dataclass(frozen=True, slots=True)
class RosterStudent:
    """A student of the group, with their subgroup (None: not assigned)."""

    user_id: UUID
    first_name: str
    last_name: str
    subgroup: int | None


@dataclass(frozen=True, slots=True)
class TeachingGroupView:
    """A group (or subgroup) the caller teaches a subject: students and lessons.

    `subgroups` lists the subgroups the caller teaches in the group; it is empty when
    they teach the group undivided.
    """

    subject_id: UUID
    subject_name: str
    group_id: UUID
    group_name: str
    subgroup: int | None
    subgroups: tuple[int, ...]
    students: list[RosterStudent]
    lessons: list[LessonRef]


@dataclass(frozen=True, slots=True)
class HomeworkEntry:
    """A homework of the subject and what the student did with it."""

    lesson_id: UUID
    date: dt.date
    due_date: dt.date | None
    text: str | None
    done_at: dt.datetime | None
    note: str | None


@dataclass(frozen=True, slots=True)
class AbsentLesson:
    """A lesson of the subject the student missed."""

    lesson_id: UUID
    date: dt.date
    excused: bool


@dataclass(frozen=True, slots=True)
class TeachingStudentView:
    """One student's record in a subject: marks, homework, attendance."""

    subject_id: UUID
    subject_name: str
    group_id: UUID
    group_name: str
    student: RosterStudent
    semester: int | None
    marks: list[MarkRef]
    average: float | None
    semester_mark: float | None
    homework: list[HomeworkEntry]
    absences: int
    lessons_with_attendance: int | None
    absent_lessons: list[AbsentLesson]
    gpa_with_temporary: float | None = None
