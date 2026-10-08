"""EMIS contracts (provider: identity process gateway)."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
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
