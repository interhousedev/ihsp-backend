"""Plain records returned by repositories to the classwork use cases."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.modules.academic.domain.classwork.lesson import Lesson


@dataclass(frozen=True, slots=True)
class StudentRecord:
    """A student, the group and the subgroup (names live in identity)."""

    user_id: UUID
    group_id: UUID
    group_name: str
    subgroup: int | None
    status: Literal["active", "left"]
    synced_at: dt.datetime | None
    current_semester: int | None


@dataclass(frozen=True, slots=True)
class TodoRecord:
    """A student's own state of a lesson's homework."""

    student_id: UUID
    lesson_id: UUID
    done_at: dt.datetime | None
    note: str | None
    updated_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class HomeworkRecord:
    """A lesson with homework and the student's to-do state, if any."""

    lesson: Lesson
    todo: TodoRecord | None


@dataclass(frozen=True, slots=True)
class MarkRecord:
    """A mark of a student for display."""

    subject_id: UUID
    subject_names: dict[str, str]
    subject_short: str | None
    semester: int
    type: str
    value: int
    date: dt.date
    lesson_id: UUID | None
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class TermRecord:
    """The dates of a term."""

    id: UUID
    starts_on: dt.date
    ends_on: dt.date


@dataclass(frozen=True, slots=True)
class JournalOption:
    """One journal a teacher can open: a subject and an audience."""

    subject_id: UUID
    subject_names: dict[str, str]
    subject_short: str | None
    audience: tuple[str, ...]
    groups: dict[UUID, str]  # names of the groups in the audience


@dataclass(frozen=True, slots=True)
class ReportRow:
    """One aggregated attendance row before names are resolved."""

    key: str
    absences: int
    excused: int
    lessons: int
    not_taken: int
    names: dict[str, str] | None = None
    text: str | None = None
    on: dt.date | None = None
    period: int | None = None


@dataclass(frozen=True, slots=True)
class SubjectStat:
    """A student's absences in one subject."""

    subject_id: UUID
    names: dict[str, str]
    short: str | None
    absences: int
    excused: int
    lessons: int


@dataclass(slots=True)
class StudentAttendanceData:
    """Raw numbers behind the student's attendance page (WEB-17)."""

    subjects: list[SubjectStat] = field(default_factory=list)
    days: list[tuple[dt.date, int]] = field(default_factory=list)
    missed: list[tuple[Lesson, bool]] = field(default_factory=list)
    not_taken: int = 0
