"""IdentityDirectory subset for the library tests (names, roles, locale)."""

import dataclasses
from collections.abc import Sequence
from uuid import UUID

from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserRef
from tests.fakes.ai.contracts import make_user


class FakeLibraryIdentity:
    """Users by id; `user_ids_with_roles` serves the librarian notifications."""

    def __init__(self, *users: UserRef) -> None:
        """Index the users."""
        self.users: dict[UUID, UserRef] = {u.id: u for u in users}

    def add(self, actor: Actor, *, first: str, last: str, locale: str = "en") -> None:
        """Register a user for an actor with the actor's roles."""
        user = make_user(*actor.roles, first=first, last=last, locale=locale)
        self.users[actor.user_id] = dataclasses.replace(user, id=actor.user_id)

    async def get_user(self, user_id: UUID) -> UserRef | None:
        """The user or None."""
        return self.users.get(user_id)

    async def get_users(self, user_ids: Sequence[UUID]) -> dict[UUID, UserRef]:
        """The known users."""
        return {u: self.users[u] for u in user_ids if u in self.users}

    async def user_ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Ids of users holding any of the roles."""
        wanted = set(roles)
        return [u.id for u in self.users.values() if u.roles & wanted]
