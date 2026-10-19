"""An in-memory IdentityDirectory for notify and admin tests."""

from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from app.shared.actor import Role
from app.shared.contracts.identity import (
    TelegramAccountRef,
    UserPreferences,
    UserRef,
    UserStatus,
)


class FakeIdentityDirectory:
    """Users, Telegram accounts and preferences kept in dictionaries."""

    def __init__(self, *, active_only: bool = False) -> None:
        """Start empty; `active_only` makes user_ids_with_roles skip inactive users."""
        self.users: dict[UUID, UserRef] = {}
        self.accounts: dict[UUID, list[TelegramAccountRef]] = {}
        self.preferences: dict[UUID, UserPreferences] = {}
        self.blocked_calls: list[tuple[int, bool]] = []
        self._active_only = active_only

    def add_user(
        self, user: UserRef, *telegram_ids: int, blocked: bool = False
    ) -> UserRef:
        """Add a user with linked Telegram accounts."""
        self.users[user.id] = user
        self.accounts[user.id] = [
            TelegramAccountRef(
                telegram_user_id=telegram_id,
                user_id=user.id,
                otp_delivery=True,
                username=None,
                blocked=blocked,
            )
            for telegram_id in telegram_ids
        ]
        return user

    async def get_user(self, user_id: UUID) -> UserRef | None:
        """Return the user or None."""
        return self.users.get(user_id)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        """Return the existing users among the ids."""
        return {uid: self.users[uid] for uid in user_ids if uid in self.users}

    async def search_users(
        self, query: str, *, roles: Sequence[Role] = (), limit: int = 20
    ) -> list[UserRef]:
        """Users matching the query by name or login (and roles, if given)."""
        needle = query.lower()
        found = [
            user
            for user in self.users.values()
            if needle in f"{user.first_name} {user.last_name} {user.login}".lower()
            and (not roles or user.roles & set(roles))
        ]
        return found[:limit]

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        """Return stored preferences or the defaults."""
        return self.preferences.get(user_id, UserPreferences())

    async def photo_urls(self, user_ids: Sequence[UUID]) -> dict[UUID, str]:
        """No user has a photo in this fake."""
        return {}

    async def user_by_telegram(self, telegram_user_id: int) -> UserRef | None:
        """Return the user a Telegram account is linked to."""
        for user_id, accounts in self.accounts.items():
            if any(a.telegram_user_id == telegram_user_id for a in accounts):
                return self.users.get(user_id)
        return None

    async def user_by_login(self, login: str) -> UserRef | None:
        """Return the active user with the login, case-insensitively."""
        needle = login.lower()
        for user in self.users.values():
            if user.login.lower() == needle and user.status == UserStatus.ACTIVE:
                return user
        return None

    async def touch_telegram(
        self, telegram_user_id: int, username: str | None, first_name: str
    ) -> None:
        """Refresh the cached Telegram username of the account."""
        for user_id, accounts in self.accounts.items():
            self.accounts[user_id] = [
                (
                    replace(account, username=username)
                    if account.telegram_user_id == telegram_user_id
                    else account
                )
                for account in accounts
            ]

    async def telegram_accounts(self, user_id: UUID) -> list[TelegramAccountRef]:
        """Return the user's accounts."""
        return list(self.accounts.get(user_id, []))

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Return ids of users holding any role."""
        return [
            user.id
            for user in self.users.values()
            if any(role in user.roles for role in roles)
            and (not self._active_only or user.status == UserStatus.ACTIVE)
        ]

    async def set_telegram_blocked(self, telegram_user_id: int, blocked: bool) -> None:
        """Flag the account as blocked or unblocked."""
        self.blocked_calls.append((telegram_user_id, blocked))
        for user_id, accounts in self.accounts.items():
            self.accounts[user_id] = [
                (
                    replace(account, blocked=blocked)
                    if account.telegram_user_id == telegram_user_id
                    else account
                )
                for account in accounts
            ]
