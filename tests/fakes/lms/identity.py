"""In-memory IdentityDirectory for LMS tests."""

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


class FakeIdentityDirectory:
    """Users kept in a dict; `add_user` creates active users."""

    def __init__(self) -> None:
        """Start with no users."""
        self.users: dict[UUID, UserRef] = {}

    def add_user(
        self,
        login: str,
        *,
        first_name: str = "Ada",
        last_name: str = "Lovelace",
        roles: Sequence[Role] = (Role.TEACHER,),
        user_id: UUID | None = None,
    ) -> UserRef:
        """Create an active user and return its reference."""
        user = UserRef(
            id=user_id or new_id(),
            login=login,
            first_name=first_name,
            last_name=last_name,
            middle_name=None,
            roles=frozenset(roles),
            status=UserStatus.ACTIVE,
            locale="en",
            emis_status=None,
        )
        self.users[user.id] = user
        return user

    async def get_user(self, user_id: UUID) -> UserRef | None:
        """Return the user or None."""
        return self.users.get(user_id)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        """Return the existing users among the ids."""
        return {uid: self.users[uid] for uid in user_ids if uid in self.users}

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        """Return default preferences."""
        return UserPreferences()

    async def user_by_telegram(self, telegram_user_id: int) -> UserRef | None:
        """No Telegram links in this fake."""
        return None

    async def user_by_login(self, login: str) -> UserRef | None:
        """Find a user by login, case-insensitively."""
        wanted = login.lower()
        return next(
            (u for u in self.users.values() if (u.login or "").lower() == wanted), None
        )

    async def telegram_accounts(self, user_id: UUID) -> list[TelegramAccountRef]:
        """No Telegram links in this fake."""
        return []

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Return ids of users holding any of the roles."""
        return [u.id for u in self.users.values() if u.roles & set(roles)]

    async def search_users(
        self, query: str, *, roles: Sequence[Role] = (), limit: int = 20
    ) -> list[UserRef]:
        """Search by login or last name."""
        needle = query.lower()
        found = [
            u
            for u in self.users.values()
            if needle in (u.login or "").lower() or needle in u.last_name.lower()
        ]
        return found[:limit]

    async def set_telegram_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        """Nothing to do."""

    async def touch_telegram(
        self, telegram_user_id: int, username: str | None, first_name: str
    ) -> None:
        """Nothing to do."""
