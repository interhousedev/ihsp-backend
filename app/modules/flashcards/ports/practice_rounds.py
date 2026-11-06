"""Port: the restart round of one set on one study day."""

from collections.abc import Sequence
from datetime import date
from typing import Protocol
from uuid import UUID


class PracticeRounds(Protocol):
    """An ordered queue of card ids per user, set and study day."""

    async def start(
        self, owner_id: UUID, set_id: UUID, day: date, card_ids: Sequence[UUID]
    ) -> None:
        """Replace the round with these cards."""
        ...

    async def remaining(self, owner_id: UUID, set_id: UUID, day: date) -> list[UUID]:
        """Return the ids still in the round, next first (empty without a round)."""
        ...

    async def answered(
        self, owner_id: UUID, set_id: UUID, day: date, card_id: UUID, *, again: bool
    ) -> None:
        """Take the card out of the round; `again` puts it back at the end."""
        ...
