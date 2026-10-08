"""Flash cards contracts (provider: flashcards module)."""

from collections.abc import Sequence
from typing import Any, Literal, Protocol
from uuid import UUID


class FlashcardsApi(Protocol):
    """Flash card sets for other modules."""

    async def list_sets(self, owner_id: UUID) -> list[dict[str, Any]]:
        """Return the owner's sets."""
        ...

    async def get_set(
        self, set_id: UUID, owner_id: UUID | None
    ) -> dict[str, Any] | None:
        """Return a set; owner_id None means a public read for shares."""
        ...

    async def create_set(
        self,
        owner_id: UUID,
        title: str,
        cards: Sequence[tuple[str, str]],
        *,
        source: Literal["manual", "ai", "mcp", "copied"],
        source_chat_id: UUID | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a set from (front, back) pairs."""
        ...

    async def add_cards(
        self, owner_id: UUID, set_id: UUID, cards: Sequence[tuple[str, str]]
    ) -> dict[str, Any]:
        """Add cards to a set."""
        ...

    async def update_card(
        self, owner_id: UUID, card_id: UUID, front: str | None, back: str | None
    ) -> dict[str, Any]:
        """Edit one card."""
        ...

    async def set_owner(self, set_id: UUID) -> UUID | None:
        """Return the owner of the set."""
        ...
