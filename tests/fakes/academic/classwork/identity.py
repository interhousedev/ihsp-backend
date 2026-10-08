"""Fake identity directory for the classwork tests."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.shared.actor import Role
from app.shared.contracts.identity import (
    TelegramAccountRef,
    UserPreferences,
    UserRef,
    UserStatus,
)
from app.shared.ids import new_id


class FakeIdentity:
    """In-memory IdentityDirectory."""

    def __init__(self) -> None:
        """Start empty."""
        self.users: dict[UUID, UserRef] = {}
        self.prefs: dict[UUID, UserPreferences] = {}

    def add(
        self,
        first_name: str,
        last_name: str,
        role: Role = Role.STUDENT,
        *,
        user_id: UUID | None = None,
        status: UserStatus = UserStatus.ACTIVE,
        locale: str = "en",
    ) -> UserRef:
        """Register a user and return the reference."""
        uid = user_id or new_id()
        user = UserRef(
            id=uid,
            login=f"{last_name}.{first_name}".lower(),
            first_name=first_name,
            last_name=last_name,
            middle_name=None,
            roles=frozenset({role}),
            status=status,
            locale=locale,
            emis_status="active",
        )
        self.users[uid] = user
        self.prefs[uid] = UserPreferences(locale=locale)
        return user

    def set_preferences(self, user_id: UUID, **fields: Any) -> UserPreferences:
        """Change some preference fields of a user."""
        current = self.prefs.get(user_id, UserPreferences())
        self.prefs[user_id] = current.model_copy(update=fields)
        return self.prefs[user_id]

    async def get_user(self, user_id: UUID) -> UserRef | None:
        """Return the user or None."""
        return self.users.get(user_id)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        """Return the known users among the ids."""
        return {uid: self.users[uid] for uid in user_ids if uid in self.users}

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        """Return stored or default preferences."""
        return self.prefs.get(user_id, UserPreferences())

    async def user_by_telegram(self, telegram_user_id: int) -> UserRef | None:
        """Not used by classwork."""
        return None

    async def user_by_login(self, login: str) -> UserRef | None:
        """Not used by classwork."""
        return None

    async def telegram_accounts(self, user_id: UUID) -> list[TelegramAccountRef]:
        """Not used by classwork."""
        return []

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Return users holding any of the roles."""
        return [u.id for u in self.users.values() if set(roles) & set(u.roles)]

    async def search_users(
        self, query: str, *, roles: Sequence[Role] = (), limit: int = 20
    ) -> list[UserRef]:
        """Not used by classwork."""
        return []

    async def set_telegram_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        """Not used by classwork."""

    async def touch_telegram(
        self, telegram_user_id: int, username: str | None, first_name: str
    ) -> None:
        """Not used by classwork."""
