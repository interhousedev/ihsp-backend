"""The flash card set entity (one owner; others copy a set)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.modules.flashcards.domain.limits import (
    DEFAULT_NEW_PER_DAY,
    DEFAULT_REVIEWS_PER_DAY,
)


class SetSource(StrEnum):
    """How a set came to be (WEB-22)."""

    MANUAL = "manual"
    AI = "ai"
    MCP = "mcp"
    COPIED = "copied"


@dataclass(slots=True)
class FlashcardSet:
    """A titled set of cards with the owner's daily limits (README → FlashcardSet)."""

    id: UUID
    owner_id: UUID
    title: str
    created_at: datetime
    source: SetSource = SetSource.MANUAL
    description: str | None = None
    source_chat_id: UUID | None = None
    copied_from_set_id: UUID | None = None
    new_per_day: int = DEFAULT_NEW_PER_DAY
    reviews_per_day: int = DEFAULT_REVIEWS_PER_DAY
    card_count: int = 0

    def owned_by(self, user_id: UUID) -> bool:
        """Return True if the user owns the set."""
        return self.owner_id == user_id


@dataclass(frozen=True, slots=True)
class SetCounts:
    """Cards of a set that count towards today's lists, before the daily limits.

    `due` is every seen card due before the day ends: `learning + review`.
    """

    new: int = 0
    due: int = 0
    learning: int = 0
    review: int = 0
