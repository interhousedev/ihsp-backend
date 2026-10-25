"""Port: reading progress (owner: the reader area)."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.library.domain.reader_progress import ReadingProgress


class ProgressRepository(Protocol):
    """Where users stopped in items."""

    async def percents(
        self, user_id: UUID, item_ids: Sequence[UUID]
    ) -> dict[UUID, float]:
        """Progress 0 to 100 of the items the user has opened (others are absent)."""
        ...

    # - - - Added by the reader area - - -

    async def get(self, user_id: UUID, item_id: UUID) -> ReadingProgress | None:
        """The user's progress in the item, or None."""
        ...

    async def save(self, progress: ReadingProgress) -> None:
        """Insert the progress or replace the existing row of the user and item."""
        ...

    async def unfinished(
        self, user_id: UUID, *, limit: int, offset: int = 0
    ) -> list[ReadingProgress]:
        """Progress below 100 percent, most recently opened first."""
        ...

    async def delete_all(self, user_id: UUID) -> int:
        """Delete all progress of the user (account closure)."""
        ...
