"""Names of people and locales through the identity directory."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.shared.contracts.identity import IdentityDirectory, UserPreferences


@dataclass(frozen=True, slots=True)
class Person:
    """A person as the API shows them (``PersonRef``)."""

    id: UUID
    first_name: str
    last_name: str

    def to_json(self) -> dict[str, Any]:
        """Return the ``PersonRef`` JSON object."""
        return {
            "id": str(self.id),
            "first_name": self.first_name,
            "last_name": self.last_name,
        }


class PeopleDirectory:
    """Looks people and preferred locales up in identity."""

    def __init__(self, identity: IdentityDirectory) -> None:
        """Store the identity directory."""
        self.identity = identity

    async def people(self, ids: Iterable[UUID]) -> dict[UUID, Person]:
        """Return the people that exist, by id."""
        unique = list(dict.fromkeys(ids))
        if not unique:
            return {}
        users = await self.identity.get_users(unique)
        return {
            user_id: Person(user_id, user.first_name, user.last_name)
            for user_id, user in users.items()
        }

    async def person(self, user_id: UUID | None) -> Person | None:
        """Return one person or None."""
        if user_id is None:
            return None
        return (await self.people([user_id])).get(user_id)

    async def preferences(self, user_id: UUID) -> UserPreferences:
        """Return the user's preferences."""
        return await self.identity.get_preferences(user_id)

    async def locale(self, user_id: UUID) -> str:
        """Return the user's language (uz, ru or en)."""
        return str((await self.preferences(user_id)).locale)
