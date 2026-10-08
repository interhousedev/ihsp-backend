"""Rows the student-facing marks views read (plain records, no ORM)."""

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StudentContext:
    """A student with the group data the views need."""

    user_id: UUID
    group_id: UUID
    group_name: str
    subgroup: int | None
    current_semester: int | None
    curriculum_subject_ids: tuple[UUID, ...]
    synced_at: dt.datetime | None
    backfilled_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class SubjectInfo:
    """A subject with its names."""

    id: UUID
    name: Mapping[str, str]
    short_name: str | None


@dataclass(frozen=True, slots=True)
class ResultRow:
    """A stored result; ``subject_id`` is None for the semester GPA row."""

    semester: int
    subject_id: UUID | None
    value: Decimal | None
    lesson_avg: Decimal | None
    midterm_avg: Decimal | None
    final_avg: Decimal | None
    emis_rating: int | None
    marks_count: int


@dataclass(frozen=True, slots=True)
class MarkRow:
    """A stored, non-removed mark."""

    subject_id: UUID
    semester: int
    type: str
    value: int
    date: dt.date
    ordinal: int
    lesson_id: UUID | None
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class LessonRow:
    """A lesson with the fields the marks views show."""

    id: UUID
    date: dt.date
    period: int
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject_id: UUID
    teacher_id: UUID | None
    room_id: UUID | None
    room_slug: str | None
    room_name: str | None
    audience: tuple[str, ...]
    status: str
    is_overridden: bool
    changes: dict[str, Any] | None
    topic: str | None
    homework_text: str | None
    attendance_roster: tuple[UUID, ...] | None
    attendance_absent: tuple[UUID, ...] | None
    attendance_excused: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class AttendanceCount:
    """Absences and counted lessons of one subject for one student."""

    absences: int
    with_attendance: int
