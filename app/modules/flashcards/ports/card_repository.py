"""Port: storage of flash cards."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.flashcards.domain.flashcard import Flashcard
from app.modules.flashcards.domain.flashcard_set import SetCounts


class FlashcardRepository(Protocol):
    """Cards of the sets."""

    async def add_many(self, cards: Sequence[Flashcard]) -> None:
        """Insert new cards."""
        ...

    async def get(self, card_id: UUID) -> Flashcard | None:
        """Return the card of any set."""
        ...

    async def get_for_update(self, card_id: UUID) -> Flashcard | None:
        """Return the card and lock its row until the transaction ends."""
        ...

    async def save(self, card: Flashcard) -> None:
        """Write the card's fields."""
        ...

    async def delete_many(self, card_ids: Sequence[UUID]) -> None:
        """Delete cards by id."""
        ...

    async def list_for_set(self, set_id: UUID) -> list[Flashcard]:
        """Return the set's cards ordered by position."""
        ...

    async def counts_for_sets(
        self, set_ids: Sequence[UUID], *, due_before: datetime
    ) -> dict[UUID, SetCounts]:
        """Return new cards and seen cards due before `due_before`, per set."""
        ...
