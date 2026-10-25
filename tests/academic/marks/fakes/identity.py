"""Fake identity directory and commands for the marks tests."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from app.shared.actor import Role
from app.shared.contracts.identity import UserPreferences, UserRef, UserStatus


def make_user(
    user_id: UUID,
    *,
    first_name: str = "Aliya",
    last_name: str = "Karimova",
    roles: frozenset[Role] = frozenset({Role.STUDENT}),
    status: UserStatus = UserStatus.ACTIVE,
    locale: str = "en",
    emis_status: str | None = "active",
) -> UserRef:
    """Build a UserRef with test defaults."""
    return UserRef(
        id=user_id,
        login=f"user.{str(user_id)[:6]}",
        first_name=first_name,
        last_name=last_name,
        middle_name=None,
        roles=roles,
        status=status,
        locale=locale,
        emis_status=emis_status,  # type: ignore[arg-type]
    )


class FakeIdentity:
    """In-memory IdentityDirectory (the parts the marks module uses)."""

    def __init__(self) -> None:
        """Start empty."""
        self.users: dict[UUID, UserRef] = {}
        self.prefs: dict[UUID, UserPreferences] = {}
        self.photos: dict[UUID, str] = {}
        self.photo_calls: list[list[UUID]] = []

    def add(self, user: UserRef, prefs: UserPreferences | None = None) -> UserRef:
        """Register a user (and optionally their preferences)."""
        self.users[user.id] = user
        if prefs is not None:
            self.prefs[user.id] = prefs
        return user

    async def get_user(self, user_id: UUID) -> UserRef | None:
        """Return the user or None."""
        return self.users.get(user_id)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        """Return the known users among the ids."""
        return {uid: self.users[uid] for uid in user_ids if uid in self.users}

    async def get_preferences(self, user_id: UUID) -> UserPreferences:
        """Return stored or default preferences."""
        return self.prefs.get(user_id, UserPreferences())

    async def photo_urls(self, user_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Return the photo URLs of the users that have one (records each call)."""
        self.photo_calls.append(list(user_ids))
        return {uid: self.photos[uid] for uid in user_ids if uid in self.photos}

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Return users holding any of the roles."""
        return [u.id for u in self.users.values() if set(roles) & set(u.roles)]


class FakeIdentityCommands:
    """Records update_names calls."""

    def __init__(self) -> None:
        """Start with no calls."""
        self.name_updates: list[tuple[UUID, dict[str, Any]]] = []

    async def update_names(
        self,
        user_id: UUID,
        *,
        first_name: str,
        last_name: str,
        middle_name: str | None,
    ) -> None:
        """Record the call."""
        self.name_updates.append(
            (
                user_id,
                {
                    "first_name": first_name,
                    "last_name": last_name,
                    "middle_name": middle_name,
                },
            )
        )
