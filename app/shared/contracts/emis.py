"""EMIS contracts (provider: identity process gateway)."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from app.shared.base_error import BaseError
from app.shared.lesson_kind import LessonKind


class EmisMarkType(StrEnum):
    """Kinds of marks in EMIS."""

    LESSON = "lesson"
    MIDTERM = "midterm"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class EmisProfile:
    """Student profile from EMIS."""

    emis_student_id: int
    first_name: str
    last_name: str
    middle_name: str | None
    institution_id: int
    group_emis_id: int
    group_name: str  # normalized, e.g. "2TN2"
    current_semester: int | None
    curriculum_id: int | None


@dataclass(frozen=True, slots=True)
class EmisSubject:
    """A subject of the student's curriculum."""

    emis_subject_id: int
    name_uz: str
    name_ru: str
    name_en: str


@dataclass(frozen=True, slots=True)
class EmisMark:
    """One mark."""

    type: EmisMarkType
    date: dt.date
    value: int


@dataclass(frozen=True, slots=True)
class EmisSubjectRatings:
    """Marks and the semester rating of one subject."""

    emis_subject_id: int
    semester: int
    semester_rating: int | None
    marks: tuple[EmisMark, ...]
    payload_hash: str  # sha256 of the canonical JSON of this response


@dataclass(frozen=True, slots=True)
class EmisClassHour:
    """One bell of EMIS ``class-hours``; ``pair_number`` is 0-based (0 = period 1)."""

    pair_number: int
    begin_time: dt.time
    end_time: dt.time


@dataclass(frozen=True, slots=True)
class EmisTeacher:
    """A teacher as the EMIS timetable names them (names normalized like students')."""

    emis_id: int | None
    first_name: str
    last_name: str
    middle_name: str | None


@dataclass(frozen=True, slots=True)
class EmisTopic:
    """The topic a teacher entered for a class, with the files and video around it."""

    name: str
    description: str | None = None
    topic_file_url: str | None = None
    homework_file_url: str | None = None
    video_url: str | None = None


@dataclass(frozen=True, slots=True)
class EmisClass:
    """One class of the student's timetable on a date (``class-schedules``).

    ``pair_number`` is 0-based like ``EmisClassHour.pair_number``. ``subgroup`` is the
    student's own half (1 or 2) when EMIS split the class, else None: the other half's
    slot only reaches IHSP through a student of that half.
    """

    class_id: int
    date: dt.date
    pair_number: int
    subject: EmisSubject
    teacher: EmisTeacher | None
    room: str | None
    subgroup: Literal[1, 2] | None
    kind: LessonKind
    topic: EmisTopic | None = None


class EmisAuthFailed(BaseError):
    """EMIS rejected the stored credentials."""

    code = "emis/auth-failed"
    status = 401
    message_key = "emis-auth-failed"


class EmisUnavailable(BaseError):
    """EMIS did not answer or answered with a server error."""

    code = "emis/unavailable"
    status = 503
    message_key = "emis-unavailable"


class EmisSource(Protocol):
    """What academic sync uses to read EMIS."""

    async def profile(self, user_id: UUID) -> EmisProfile:
        """Return the student's profile."""
        ...

    async def subjects(self, user_id: UUID) -> list[EmisSubject]:
        """Return the student's subjects."""
        ...

    async def ratings(
        self, user_id: UUID, emis_subject_id: int, semester: int
    ) -> EmisSubjectRatings:
        """Return marks and rating of one subject in one semester."""
        ...

    async def class_hours(self, user_id: UUID) -> list[EmisClassHour]:
        """Return the bells of the lyceum (the same for every student)."""
        ...

    async def timetable(
        self, user_id: UUID, begin: dt.date, end: dt.date
    ) -> list[EmisClass]:
        """Return the student's classes on the dates begin..end (inclusive)."""
        ...
