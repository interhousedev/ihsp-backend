"""In-memory IdentityDirectory with just the users the LMS tests need."""

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
    """Users by id; `add` creates active users with readable names."""

    def __init__(self) -> None:
        self.users: dict[UUID, UserRef] = {}

    def add(
        self,
        user_id: UUID | None = None,
        *,
        first_name: str = "Ada",
        last_name: str = "Lovelace",
    ) -> UserRef:
        """Register a user and return it."""
        user = UserRef(
            id=user_id or new_id(),
            login=f"{last_name}.{first_name}".lower(),
            first_name=first_name,
            last_name=last_name,
            middle_name=None,
            roles=frozenset({Role.STUDENT}),
            status=UserStatus.ACTIVE,
            locale="en",
            emis_status=None,
        )
        self.users[user.id] = user
        return user

    async def get_user(self, user_id: UUID) -> UserRef | None:
        return self.users.get(user_id)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        return {uid: self.users[uid] for uid in user_ids if uid in self.users}

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        return UserPreferences()

    async def user_by_telegram(self, telegram_user_id: int) -> UserRef | None:
        return None

    async def user_by_login(self, login: str) -> UserRef | None:
        return next((u for u in self.users.values() if u.login == login.lower()), None)

    async def telegram_accounts(self, user_id: UUID) -> list[TelegramAccountRef]:
        return []

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        return [u.id for u in self.users.values() if u.roles & set(roles)]

    async def search_users(
        self, query: str, *, roles: Sequence[Role] = (), limit: int = 20
    ) -> list[UserRef]:
        return list(self.users.values())[:limit]

    async def set_telegram_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        return None

    async def touch_telegram(
        self, telegram_user_id: int, username: str | None, first_name: str
    ) -> None:
        return None
