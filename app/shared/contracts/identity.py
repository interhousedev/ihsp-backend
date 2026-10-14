"""Identity contracts (provider: identity module)."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from app.shared.actor import Role

from pydantic import BaseModel, EmailStr, Field, field_validator

BOTTOM_NAV_MAX = 4
SP_BOTTOM_NAV_IDS: tuple[str, ...] = (
    "dashboard",
    "today",
    "timetable",
    "subjects",
    "grades",
    "attendance",
    "homework",
    "exams",
    "assistant",
    "notebooks",
    "flashcards",
    "files",
    "links",
    "notifications",
    "settings",
)


class UserStatus(StrEnum):
    """Lifecycle of a user account."""

    UNREGISTERED = "unregistered"
    PENDING_ACTIVATION = "pending_activation"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DEACTIVATED = "deactivated"
    PENDING_DELETION = "pending_deletion"
    """The owner asked to delete it; restorable at login until the purge."""
    DELETED = "deleted"


_TELEGRAM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_PHONE_RE = re.compile(r"^\+?[0-9 ()\-]{7,24}$")
_PHONE_DIGITS = (7, 15)


class TeacherContacts(BaseModel):
    """A teacher's public contacts, shown to the students they teach."""

    telegram: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=24)
    office_hours: str | None = Field(default=None, max_length=200)
    office: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)

    @field_validator(
        "telegram", "email", "phone", "office_hours", "office", "note", mode="before"
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """Trim text; an empty string means "not set"."""
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("telegram")
    @classmethod
    def _check_telegram(cls, value: str | None) -> str | None:
        """Accept @name, t.me/name or name; store the bare username."""
        if value is None:
            return None
        name = re.sub(r"^(https?://)?(t\.me/)?@?", "", value)
        if not _TELEGRAM_RE.match(name):
            raise ValueError("telegram: 5-32 letters, digits or underscores")
        return name

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        """7-15 digits with an optional leading plus."""
        if value is None:
            return None
        digits = sum(ch.isdigit() for ch in value)
        if not _PHONE_RE.match(value) or not (
            _PHONE_DIGITS[0] <= digits <= _PHONE_DIGITS[1]
        ):
            raise ValueError("phone: 7-15 digits, optional leading +")
        return value


class UserPreferences(BaseModel):
    """User settings (spec → Models → User → preferences)."""

    locale: Literal["uz", "ru", "en"] = "ru"
    theme: Literal["system", "light", "dark"] = "light"
    marks_enabled: bool = True
    marks_types: list[Literal["lesson", "midterm", "final"]] = [
        "lesson",
        "midterm",
        "final",
    ]
    marks_values: list[int] = [2, 3, 4, 5]
    marks_subject_ids: list[UUID] | None = None
    alerts_drops: bool = True
    alerts_gpa_below: float | None = None
    alerts_semester_mark_below: float | None = None
    alerts_mark_below: int | None = None
    lessons_links_lead_min: int = 5
    lessons_prompt_enabled: bool = True
    mail_forward_to_telegram: bool = True
    notify_push: bool = True  # Web Push is a second channel next to Telegram
    today_cards: list[str] = [
        "now",
        "timeline",
        "due",
        "marks",
        "semester",
        "announcements",
        "alerts",
    ]
    onboarding_dismissed: list[str] = []
    bottom_nav: list[str] | None = None  # sp phone bottom bar: up to 4 destination ids
    seen_marks_at: datetime | None = None
    contacts: TeacherContacts = TeacherContacts()  # teachers: shown to students

    @field_validator("bottom_nav")
    @classmethod
    def _check_bottom_nav(cls, value: list[str] | None) -> list[str] | None:
        """At most 4 distinct ids, all from SP_BOTTOM_NAV_IDS."""
        if value is None:
            return None
        if len(value) > BOTTOM_NAV_MAX or len(set(value)) != len(value):
            raise ValueError("bottom_nav: up to 4 distinct ids")
        if not set(value) <= set(SP_BOTTOM_NAV_IDS):
            raise ValueError("bottom_nav: unknown destination")
        return value


@dataclass(frozen=True, slots=True)
class UserRef:
    """Read-only view of a user for other modules."""

    id: UUID
    login: str | None
    first_name: str
    last_name: str
    middle_name: str | None
    roles: frozenset[Role]
    status: UserStatus
    locale: str
    emis_status: Literal["active", "needs_reauth"] | None
    photo_file_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class TelegramAccountRef:
    """A Telegram account linked to a user."""

    telegram_user_id: int
    user_id: UUID
    otp_delivery: bool
    username: str | None
    blocked: bool


class IdentityDirectory(Protocol):
    """Read access to users and their Telegram links."""

    async def get_user(self, user_id: UUID) -> UserRef | None:
        """Return the user or None."""
        ...

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        """Return the existing users among the ids."""
        ...

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        """Return the user's preferences with defaults filled in."""
        ...

    async def photo_urls(self, user_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Return short-lived photo URLs; users without a photo are left out."""
        ...

    async def user_by_telegram(self, telegram_user_id: int) -> UserRef | None:
        """Return the user a Telegram account is linked to."""
        ...

    async def user_by_login(self, login: str) -> UserRef | None:
        """Find an active user by login, case-insensitively."""
        ...

    async def telegram_accounts(self, user_id: UUID) -> list[TelegramAccountRef]:
        """Return the Telegram accounts linked to the user."""
        ...

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Return ids of active users holding any of the roles."""
        ...

    async def search_users(
        self, query: str, *, roles: Sequence[Role] = (), limit: int = 20
    ) -> list[UserRef]:
        """Search users by name or login."""
        ...

    async def set_telegram_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        """Mark that a Telegram account blocked the bot."""
        ...

    async def touch_telegram(
        self, telegram_user_id: int, username: str | None, first_name: str
    ) -> None:
        """Refresh the cached Telegram username and name."""
        ...


class IdentityCommands(Protocol):
    """Write access to users for other modules."""

    async def create_unregistered_student(
        self,
        *,
        first_name: str,
        last_name: str,
        middle_name: str | None,
        emis_student_id: int | None,
    ) -> UserRef:
        """Create a student who has not registered yet (EMIS import)."""
        ...

    async def ensure_teacher(
        self,
        *,
        emis_teacher_id: int | None,
        first_name: str,
        last_name: str,
        middle_name: str | None,
    ) -> UserRef:
        """Find or create a teacher named by an EMIS timetable.

        Found by EMIS teacher id, else by name; a new account is a staff account
        waiting for activation, without an email (ID-10).
        """
        ...

    async def set_emis_status(
        self, user_id: UUID, status: Literal["active", "needs_reauth"]
    ) -> None:
        """Set whether the stored EMIS password still works."""
        ...

    async def update_names(
        self,
        user_id: UUID,
        *,
        first_name: str,
        last_name: str,
        middle_name: str | None,
    ) -> None:
        """Update the user's names from EMIS."""
        ...

    async def update_preferences(
        self, user_id: UUID, patch: dict[str, Any]
    ) -> UserPreferences:
        """Merge a partial preferences dict and return the result."""
        ...

    async def unlink_telegram(self, telegram_user_id: int) -> None:
        """Remove a Telegram link."""
        ...

    async def close_account(self, user_id: UUID, *, reason: str) -> None:
        """Start closing the account."""
        ...
