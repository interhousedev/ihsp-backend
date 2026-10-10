"""Port: authors and tags of the catalogue (fuzzy search, get-or-create, item links)."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.library.domain.catalogue_labels import Author, Tag, TagCount


class LabelRepository(Protocol):
    """Authors and tags, matched by their loose key."""

    async def search_authors(self, text: str, *, limit: int) -> list[Author]:
        """Authors whose key contains the text or is close to it, best first."""
        ...

    async def search_tags(self, text: str, *, limit: int) -> list[TagCount]:
        """Tags matching the text (all when empty) with item counts, best first."""
        ...

    async def ensure_authors(self, names: Sequence[str]) -> list[Author]:
        """The authors of the names in order; unknown ones are created."""
        ...

    async def ensure_tags(self, names: Sequence[str]) -> list[Tag]:
        """The tags of the names in order; unknown ones are created."""
        ...

    async def set_item_authors(self, item_id: UUID, names: Sequence[str]) -> None:
        """Replace the author links of the item, creating authors that are new."""
        ...

    async def set_item_tags(self, item_id: UUID, names: Sequence[str]) -> None:
        """Replace the tag links of the item, creating tags that are new."""
        ...

    async def item_tags(self, item_ids: Sequence[UUID]) -> dict[UUID, list[str]]:
        """Tag names of each item, alphabetically (items without tags are absent)."""
        ...
