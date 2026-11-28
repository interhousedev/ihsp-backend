"""The digital student card: what it shows and its permanent QR token."""

import secrets
from dataclasses import dataclass
from datetime import date
from uuid import UUID

TOKEN_BYTES = 24
"""Random bytes of a QR token (32 URL-safe characters)."""


@dataclass(frozen=True, slots=True)
class LyceumName:
    """The institution name in the three languages, as EMIS gives it."""

    uz: str
    ru: str
    en: str


@dataclass(frozen=True, slots=True)
class StudentCard:
    """What a student shows as proof of study."""

    first_name: str
    last_name: str
    middle_name: str | None
    student_id: str | None
    group: str | None
    course: int | None
    academic_year: str
    org_name: str
    lyceum_name: LyceumName | None
    direction: str | None
    speciality: str | None
    has_photo: bool

    @property
    def full_name(self) -> str:
        """Surname, name and patronymic, as on a paper card."""
        parts = (self.last_name, self.first_name, self.middle_name or "")
        return " ".join(part for part in parts if part)


@dataclass(frozen=True, slots=True)
class WalletAvailability:
    """Which wallets the server can issue a pass for."""

    apple: bool
    google: bool


@dataclass(frozen=True, slots=True)
class OwnCard:
    """The student's own card with its QR token."""

    card: StudentCard
    qr_token: str
    wallet: WalletAvailability


@dataclass(frozen=True, slots=True)
class WalletPass:
    """Everything a wallet pass is made of."""

    serial: str
    card: StudentCard
    verify_url: str
    photo: bytes | None
    logo: bytes | None
    logo_url: str | None


def course_of(semester: int | None) -> int | None:
    """Return the course of a semester: 1-2 is the first course, 3-4 the second."""
    if semester is None or semester < 1:
        return None
    return (semester + 1) // 2


def academic_year_of(today: date) -> str:
    """Return the academic year of a day; a year starts on 1 September."""
    start = today.year if today.month >= 9 else today.year - 1
    return f"{start}–{start + 1}"


def new_card_token() -> str:
    """Return a fresh opaque QR token."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def card_url(share_origin: str, token: str) -> str:
    """Return the public verification address behind a QR token."""
    return f"{share_origin.rstrip('/')}/card/?t={token}"


def owner_key(user_id: UUID) -> str:
    """Return the wallet serial of a student (stable across token changes)."""
    return f"card-{user_id.hex}"
