"""Port: UniLibrary feeds, the subject-to-field map and stored-record lookups."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ExternalSource
from app.modules.library.domain.external_feed import Feed, FieldMapEntry


class ExternalRepository(Protocol):
    """The tables of the external area; the items themselves are `ItemRepository`."""

    # - - - Stored records - - -

    async def item_ids_by_external(
        self, source: ExternalSource, external_ids: Sequence[str]
    ) -> dict[str, UUID]:
        """Item ids of the records already stored (others are absent)."""
        ...

    async def add_pinned(self, item: Item) -> None:
        """Store a new external item (a pin); the session stays usable after a clash.

        Raises `DuplicateItemError` when the record is stored already, for example
        because someone pinned it a moment earlier.
        """
        ...

    async def hidden_item_ids(self, *, limit: int) -> list[UUID]:
        """Stored external items a librarian hid: unpublished or `hidden`."""
        ...

    # - - - Feeds (storage only) - - -

    async def list_feeds(self) -> list[Feed]:
        """All feeds, oldest first."""
        ...

    async def get_feed(self, feed_id: UUID) -> Feed | None:
        """The feed or None."""
        ...

    async def add_feed(self, feed: Feed) -> None:
        """Insert a feed."""
        ...

    async def save_feed(self, feed: Feed) -> None:
        """Update a feed."""
        ...

    async def delete_feed(self, feed_id: UUID) -> bool:
        """Remove a feed; False when there was none."""
        ...

    # - - - Subject to field map - - -

    async def field_map(self) -> list[FieldMapEntry]:
        """The whole map, ordered by field then subject."""
        ...

    async def replace_field_map(self, entries: Sequence[FieldMapEntry]) -> None:
        """Replace the whole map."""
        ...
