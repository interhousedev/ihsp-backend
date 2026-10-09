"""Port: topics and collections (taxonomy area)."""

from collections.abc import Collection as AbstractCollection
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.library.domain.taxonomy_collections import Collection
from app.modules.library.domain.taxonomy_topics import Topic


class TaxonomyRepository(Protocol):
    """Topics of the subjects and the curated collections."""

    async def topic_names(
        self, topic_ids: Sequence[UUID]
    ) -> dict[UUID, dict[str, str]]:
        """Names `{uz, ru, en}` of the existing topics (unknown ids are absent)."""
        ...

    # - - - Topics - - -

    async def topics(self, subject_id: UUID | None = None) -> list[Topic]:
        """The topics of one subject, or of all subjects, by position."""
        ...

    async def get_topic(self, topic_id: UUID) -> Topic | None:
        """The topic or None."""
        ...

    async def add_topic(self, topic: Topic) -> None:
        """Insert a topic."""
        ...

    async def save_topic(self, topic: Topic) -> None:
        """Update name, slug, parent, position and year of a topic."""
        ...

    async def delete_topic(self, topic_id: UUID) -> None:
        """Delete the topic; its children and item links go with it (cascade)."""
        ...

    async def count_item_links(self, topic_ids: AbstractCollection[UUID]) -> int:
        """How many item-to-topic links the topics have."""
        ...

    # - - - Collections - - -

    async def collections(self, *, published_only: bool) -> list[Collection]:
        """Collections by position (only the published ones when asked)."""
        ...

    async def get_collection(self, collection_id: UUID) -> Collection | None:
        """The collection or None."""
        ...

    async def get_collection_by_slug(self, slug: str) -> Collection | None:
        """The collection with this slug or None."""
        ...

    async def add_collection(self, collection: Collection) -> None:
        """Insert a collection (its items are separate)."""
        ...

    async def save_collection(self, collection: Collection) -> None:
        """Update title, description, cover, flag and position."""
        ...

    async def delete_collection(self, collection_id: UUID) -> None:
        """Delete the collection and its item rows."""
        ...

    async def collection_item_ids(
        self, collection_ids: Sequence[UUID]
    ) -> dict[UUID, list[UUID]]:
        """Item ids of each collection in order (empty collections are absent)."""
        ...

    async def set_collection_items(
        self, collection_id: UUID, item_ids: Sequence[UUID]
    ) -> None:
        """Replace the items of the collection, keeping the given order."""
        ...

    async def next_collection_position(self) -> int:
        """The position that puts a new collection last."""
        ...
