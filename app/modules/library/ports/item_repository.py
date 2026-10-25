"""Port: items with their details and files, subject and topic tags, history."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.modules.library.domain.catalogue_search import (
    ItemFilters,
    SearchHit,
    Viewer,
)
from app.modules.library.domain.entities import (
    Item,
    ItemEvent,
    ItemFile,
    SubjectLink,
    TopicLink,
)
from app.modules.library.domain.enums import EventKind, ExternalSource, ItemStatus


class ItemRepository(Protocol):
    """Items of all kinds. `get*` load the details of the kind and the files.

    Owner of the port: the catalogue area. Other areas may call these methods; the
    catalogue adds search and listing methods below the marked line.
    """

    async def add(self, item: Item) -> None:
        """Insert the item with its details and files (tag links are separate)."""
        ...

    async def get(self, item_id: UUID, *, lock: bool = False) -> Item | None:
        """The item or None; `lock` takes a row lock for a status change."""
        ...

    async def get_by_slug(self, slug: str) -> Item | None:
        """The item with this slug or None."""
        ...

    async def get_many(self, item_ids: Sequence[UUID]) -> dict[UUID, Item]:
        """The existing items (absent ids are missing from the result)."""
        ...

    async def get_by_external(
        self, source: ExternalSource, external_id: str
    ) -> Item | None:
        """The stored copy of an external record or None."""
        ...

    async def save(self, item: Item) -> None:
        """Update the item row and the details of its kind (files are separate)."""
        ...

    async def add_file(self, item_file: ItemFile) -> None:
        """Attach a file to the item."""
        ...

    async def save_file(self, item_file: ItemFile) -> None:
        """Update a file row (text status, pages, toc, hash)."""
        ...

    async def remove_file(self, item_id: UUID, file_id: UUID) -> None:
        """Detach a file from the item."""
        ...

    async def subject_links(
        self, item_ids: Sequence[UUID]
    ) -> dict[UUID, list[SubjectLink]]:
        """Subject tags of the items (items without tags are absent)."""
        ...

    async def set_subject_links(
        self, item_id: UUID, links: Sequence[SubjectLink]
    ) -> None:
        """Replace the subject tags of the item."""
        ...

    async def topic_links(
        self, item_ids: Sequence[UUID]
    ) -> dict[UUID, list[TopicLink]]:
        """Topic tags of the items (items without tags are absent)."""
        ...

    async def set_topic_links(self, item_id: UUID, links: Sequence[TopicLink]) -> None:
        """Replace the topic tags of the item."""
        ...

    async def find_by_file_hash(
        self, sha256: str, *, exclude: UUID | None = None
    ) -> list[UUID]:
        """Ids of items with a file of this SHA-256."""
        ...

    async def find_by_content_hash(
        self, content_hash: str, *, exclude: UUID | None = None
    ) -> list[UUID]:
        """Ids of items whose extracted text has this hash."""
        ...

    # - - - Added by the catalogue area (search, listing, queues) - - -

    async def search(
        self, filters: ItemFilters, viewer: Viewer, *, limit: int, offset: int
    ) -> list[SearchHit]:
        """Items the viewer may see that match, best first; at most `limit` rows.

        Full-text hits carry the snippet and the page. Visibility is the SQL form of
        `domain.access.can_view`, so hidden, held and unpublished items never leak.
        """
        ...

    async def subject_counts(self, viewer: Viewer) -> dict[UUID, int]:
        """Number of listed items per subject (published, not hidden, audience)."""
        ...

    async def list_books(
        self,
        *,
        query: str | None,
        status: ItemStatus | None,
        limit: int,
        offset: int,
    ) -> list[UUID]:
        """Ids of books in any status for the librarian table, newest change first."""
        ...

    async def sitemap_entries(self, *, limit: int) -> list[tuple[str, datetime]]:
        """Slug and last change of the public published books and materials."""
        ...

    async def collection_ids(self, item_id: UUID) -> list[UUID]:
        """Collections the item is on."""
        ...


class EventRepository(Protocol):
    """Append-only history of items."""

    async def append(
        self,
        item_id: UUID,
        kind: EventKind,
        *,
        at: datetime,
        actor_id: UUID | None = None,
        data: dict[str, Any] | None = None,
    ) -> ItemEvent:
        """Add an event with the next sequence number of the item."""
        ...

    async def history(self, item_id: UUID) -> list[ItemEvent]:
        """The events of the item, oldest first."""
        ...
