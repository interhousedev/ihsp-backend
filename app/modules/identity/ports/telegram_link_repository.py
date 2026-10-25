"""Port: persistence of Telegram links."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.telegram_link import TelegramLink


class TelegramLinkRepository(Protocol):
    """Reads and writes Telegram links."""

    async def get(self, telegram_user_id: int) -> TelegramLink | None:
        """Return the link of a Telegram account."""
        ...

    async def list_for_user(self, user_id: UUID) -> list[TelegramLink]:
        """Links of a user, oldest first."""
        ...

    async def list_for_users(
        self, user_ids: Sequence[UUID]
    ) -> dict[UUID, list[TelegramLink]]:
        """Links of several users."""
        ...

    async def add(self, link: TelegramLink) -> None:
        """Insert a link."""
        ...

    async def save(self, link: TelegramLink) -> None:
        """Write every field of an existing link."""
        ...

    async def delete(self, telegram_user_id: int) -> bool:
        """Delete a link; True if it existed."""
        ...

    async def delete_all_for_user(self, user_id: UUID) -> list[TelegramLink]:
        """Delete every link of a user and return them."""
        ...
