"""Flash cards contracts (provider: flashcards module)."""

from collections.abc import Sequence
from typing import Any, Literal, Protocol
from uuid import UUID

# (front, back) or (front, back, hardness), hardness being easy, medium or hard.
CardTuple = tuple[str, str] | tuple[str, str, str]


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
        cards: Sequence[CardTuple],
        *,
        source: Literal["manual", "ai", "mcp", "copied"],
        source_chat_id: UUID | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a set from (front, back) or (front, back, hardness) tuples."""
        ...

    async def add_cards(
        self, owner_id: UUID, set_id: UUID, cards: Sequence[CardTuple]
    ) -> dict[str, Any]:
        """Add a batch of cards to a set."""
        ...

    async def update_card(
        self,
        owner_id: UUID,
        card_id: UUID,
        front: str | None,
        back: str | None,
        *,
        hardness: str | None = None,
    ) -> dict[str, Any]:
        """Edit one card."""
        ...

    async def delete_card(self, owner_id: UUID, card_id: UUID) -> None:
        """Delete one card."""
        ...

    async def update_set_settings(
        self,
        owner_id: UUID,
        set_id: UUID,
        *,
        shuffle: bool | None = None,
        new_per_day: int | None = None,
        reviews_per_day: int | None = None,
    ) -> dict[str, Any]:
        """Change shuffle and the daily counts; omitted values stay."""
        ...

    async def merge_sets(
        self,
        owner_id: UUID,
        set_ids: Sequence[UUID],
        title: str,
        *,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new set from the cards of 2-20 of the owner's sets."""
        ...

    async def restart_study(self, owner_id: UUID, set_id: UUID) -> dict[str, Any]:
        """Start a practice round today; the schedule stays untouched."""
        ...

    async def card_stats(self, owner_id: UUID, set_id: UUID) -> list[dict[str, Any]]:
        """Return the statistics of every card of a set."""
        ...

    async def set_owner(self, set_id: UUID) -> UUID | None:
        """Return the owner of the set."""
        ...
