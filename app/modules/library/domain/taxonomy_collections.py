"""Collections: librarian-curated shelves not tied to a subject (LIB-4)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.library.domain.taxonomy_errors import CollectionTooLongError
from app.modules.library.domain.taxonomy_topics import (
    clean_names,
    clean_optional_names,
)

COLLECTION_MAX_ITEMS = 300


@dataclass(slots=True)
class Collection:
    """A collection; its items are stored apart, in order."""

    id: UUID
    slug: str
    title: dict[str, str]
    description: dict[str, str]
    published: bool
    position: int
    created_at: datetime
    updated_at: datetime
    cover_file_id: UUID | None = None


def clean_title(title: Mapping[str, str]) -> dict[str, str]:
    """The title in all languages; at least one must be filled."""
    return clean_names(title)


def clean_description(description: Mapping[str, str] | None) -> dict[str, str]:
    """The description in all languages, or an empty dict when nothing was written."""
    return clean_optional_names(description)


def check_item_count(count: int) -> None:
    """Refuse a collection with more than `COLLECTION_MAX_ITEMS` items."""
    if count > COLLECTION_MAX_ITEMS:
        raise CollectionTooLongError(params={"max": COLLECTION_MAX_ITEMS})
