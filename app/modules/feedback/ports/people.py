"""Port: who reporters and administrators are, and how to reach them."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Person:
    """A user as feedback shows them.

    ``login`` is None for users without a mailbox; ``has_telegram`` is True when a
    Telegram account that is not blocked is linked.
    """

    user_id: UUID
    display_name: str
    roles: tuple[str, ...]
    locale: str
    group_name: str | None = None
    login: str | None = None
    has_telegram: bool = False


class PeopleDirectory(Protocol):
    """Reads users (identity) and their groups (academic)."""

    async def person(self, user_id: UUID) -> Person | None:
        """Return the user or None."""
        ...

    async def people(self, user_ids: Sequence[UUID]) -> dict[UUID, Person]:
        """Return the users that exist."""
        ...

    async def admin_ids(self) -> list[UUID]:
        """Return every administrator."""
        ...


class FeedbackMailer(Protocol):
    """Sends a response by mail through the mail module."""

    async def send(
        self, *, sender_id: UUID, to_login: str, subject: str, html: str
    ) -> None:
        """Queue the mail from the sender's mailbox to the login's address.

        Raises on any failure (no mailbox, suspended, limits).
        """
        ...
