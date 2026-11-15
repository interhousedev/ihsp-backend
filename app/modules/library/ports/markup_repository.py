"""Port: page markup (owner: the reader area). Every method is scoped to one user."""

from typing import Protocol
from uuid import UUID

from app.modules.library.domain.reader_markup import Markup


class MarkupRepository(Protocol):
    """Private markup, one document per user and item; nobody reads another user's."""

    async def get(self, user_id: UUID, item_id: UUID) -> Markup | None:
        """The user's markup of the item, or None."""
        ...

    async def save(self, markup: Markup) -> None:
        """Insert the document or replace the user's document of the item."""
        ...

    async def delete(self, user_id: UUID, item_id: UUID) -> None:
        """Remove the user's markup of the item (nothing to do when there is none)."""
        ...

    async def delete_all(self, user_id: UUID) -> int:
        """Delete all markup of the user (account closure)."""
        ...
