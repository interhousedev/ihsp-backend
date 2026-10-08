"""EMIS contracts (provider: identity process gateway)."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from app.shared.base_error import BaseError


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
class EmisTimetableItem:
    """One cell of a group's weekly timetable in EMIS.

    ``weekday`` is ISO (1 = Monday ... 6 = Saturday). ``pair_number`` is 0-based like
    ``EmisClassHour.pair_number`` (0 = period 1). ``subgroup`` is the half (1 or 2) or
    None for the whole group. ``week_parity`` is relative to the term's first Monday.
    """

    weekday: int
    pair_number: int
    subject_emis_id: int | None
    subject_name: str
    teacher: EmisTeacher | None
    room: str | None
    subgroup: Literal[1, 2] | None = None
    week_parity: Literal["every", "odd", "even"] = "every"


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

    async def timetable(self, user_id: UUID) -> list[EmisTimetableItem]:
        """Return the weekly timetable of the student's group."""
        ...
