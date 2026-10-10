"""In-memory IdentityDirectory (only what the links module calls is meaningful)."""

from collections.abc import Sequence
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
    """Users in a dict; search matches login and names."""

    def __init__(self) -> None:
        """Start with no users."""
        self.users: dict[UUID, UserRef] = {}

    def add(
        self,
        first_name: str,
        last_name: str,
        *,
        login: str | None = None,
        user_id: UUID | None = None,
        roles: frozenset[Role] = frozenset({Role.STUDENT}),
    ) -> UserRef:
        """Create and store a user."""
        user = UserRef(
            id=user_id or new_id(),
            login=login or f"{last_name}.{first_name}".lower(),
            first_name=first_name,
            last_name=last_name,
            middle_name=None,
            roles=roles,
            status=UserStatus.ACTIVE,
            locale="ru",
            emis_status=None,
        )
        self.users[user.id] = user
        return user

    async def get_user(self, user_id: UUID) -> UserRef | None:
        """Return the user or None."""
        return self.users.get(user_id)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        """Return the users that exist."""
        return {i: self.users[i] for i in user_ids if i in self.users}

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        """Return default preferences."""
        return UserPreferences()

    async def photo_urls(self, user_ids: Sequence[UUID]) -> dict[UUID, str]:
        """No user has a photo in this fake."""
        return {}

    async def user_by_telegram(self, telegram_user_id: int) -> UserRef | None:
        """Find nobody."""
        return None

    async def user_by_login(self, login: str) -> UserRef | None:
        """Find a user by login, ignoring case."""
        for user in self.users.values():
            if user.login and user.login.lower() == login.lower():
                return user
        return None

    async def telegram_accounts(self, user_id: UUID) -> list[TelegramAccountRef]:
        """Return no accounts."""
        return []

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Return users holding any of the roles."""
        return [u.id for u in self.users.values() if u.roles & set(roles)]

    async def search_users(
        self, query: str, *, roles: Sequence[Role] = (), limit: int = 20
    ) -> list[UserRef]:
        """Match the query against login and names."""
        needle = query.lower()
        found = [
            user
            for user in self.users.values()
            if needle in (user.login or "").lower()
            or needle in user.first_name.lower()
            or needle in user.last_name.lower()
        ]
        return found[:limit]

    async def set_telegram_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        """Do nothing."""

    async def touch_telegram(
        self, telegram_user_id: int, username: str | None, first_name: str
    ) -> None:
        """Do nothing."""
