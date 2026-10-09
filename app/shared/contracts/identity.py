"""Identity contracts (provider: identity module)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from app.shared.actor import Role

from pydantic import BaseModel


class UserStatus(StrEnum):
    """Lifecycle of a user account."""

    UNREGISTERED = "unregistered"
    PENDING_ACTIVATION = "pending_activation"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DEACTIVATED = "deactivated"
    DELETED = "deleted"


class UserPreferences(BaseModel):
    """User settings (README → Models → User → preferences)."""

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
    seen_marks_at: datetime | None = None


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
