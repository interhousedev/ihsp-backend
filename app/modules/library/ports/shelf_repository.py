"""Port: the shelf (owner: the reader area)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.library.domain.enums import ShelfState
from app.modules.library.domain.reader_shelf import ShelfEntry


@dataclass(frozen=True, slots=True)
class ShelfCursor:
    """Continue the shelf after this entry (newest first)."""

    updated_at: datetime
    item_id: UUID


class ShelfRepository(Protocol):
    """Items on users' shelves."""

    async def states(
        self, user_id: UUID, item_ids: Sequence[UUID]
    ) -> dict[UUID, ShelfState]:
        """Shelf state of the items on the user's shelf (others are absent)."""
        ...

    # - - - Added by the reader area - - -

    async def get(self, user_id: UUID, item_id: UUID) -> ShelfEntry | None:
        """The entry or None."""
        ...

    async def save(self, entry: ShelfEntry) -> None:
        """Insert the entry or replace the state of the existing one."""
        ...

    async def remove(self, user_id: UUID, item_id: UUID) -> bool:
        """Delete the entry; True when there was one."""
        ...

    async def list_page(
        self,
        user_id: UUID,
        *,
        state: ShelfState | None,
        after: ShelfCursor | None,
        limit: int,
    ) -> list[ShelfEntry]:
        """Entries, most recently changed first, continuing after the cursor."""
        ...

    async def counts(
        self, user_id: UUID, *, listed_only: bool = False
    ) -> dict[ShelfState, int]:
        """How many entries are in each state (states without entries are absent).

        `listed_only` leaves out entries of items that are not listed (taken down,
        held, unpublished or hidden): those stay on the shelf as "removed" rows.
        """
        ...

    async def delete_all(self, user_id: UUID) -> int:
        """Delete the whole shelf of the user (account closure)."""
        ...
