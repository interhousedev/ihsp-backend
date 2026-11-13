"""The digital student card: what it shows and how its share token is stored."""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

CARD_TTL_SECONDS = 120
CARD_REFRESH_SECONDS = 60


@dataclass(frozen=True, slots=True)
class LyceumName:
    """The institution name in the three languages."""

    uz: str
    ru: str
    en: str


@dataclass(frozen=True, slots=True)
class StudentCard:
    """What a student shows as proof of study."""

    first_name: str
    last_name: str
    group: str | None
    course: int | None
    lyceum_name: LyceumName | None
    direction: str | None
    speciality: str | None
    has_photo: bool


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A fresh share token and when it stops working."""

    token: str
    expires_at: datetime
    refresh_in: int


@dataclass(frozen=True, slots=True)
class SharedCard:
    """A card seen through a token: the owner is never part of it."""

    card: StudentCard
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CardSnapshot:
    """The stored snapshot behind a token (the user id never leaves the server)."""

    user_id: UUID
    photo_file_id: UUID | None
    card: StudentCard
    expires_at: datetime


def course_of(semester: int | None) -> int | None:
    """Return the course of a semester: 1-2 is the first course, 3-4 the second."""
    if semester is None or semester < 1:
        return None
    return (semester + 1) // 2


def token_key(token: str) -> str:
    """Return the store key of a token: only the SHA-256 of it is ever stored."""
    return "student-card:" + hashlib.sha256(token.encode()).hexdigest()
