"""Port: storage of flash card sets."""

from typing import Protocol
from uuid import UUID

from app.modules.flashcards.domain.flashcard_set import FlashcardSet


class FlashcardSetRepository(Protocol):
    """Sets of the students."""

    async def add(self, flashcard_set: FlashcardSet) -> None:
        """Insert a new set."""
        ...

    async def get(self, set_id: UUID) -> FlashcardSet | None:
        """Return the set of any owner."""
        ...

    async def get_for_update(self, set_id: UUID) -> FlashcardSet | None:
        """Return the set and lock its row until the transaction ends."""
        ...

    async def save(self, flashcard_set: FlashcardSet) -> None:
        """Write the set's fields."""
        ...

    async def delete(self, set_id: UUID) -> None:
        """Delete the set with all its cards."""
        ...

    async def list_for_owner(self, owner_id: UUID) -> list[FlashcardSet]:
        """Return the owner's sets, newest first."""
        ...
