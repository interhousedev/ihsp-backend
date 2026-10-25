"""Change a knowledge entry (administrator)."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.modules.knowledge.application.entry_indexer import EntryIndexer
from app.modules.knowledge.domain.entry import (
    KnowledgeEntry,
    embed_text,
    normalize_key,
    normalize_tags,
    normalize_title,
    normalize_value,
    text_hash,
)
from app.modules.knowledge.domain.errors import (
    KnowledgeEntryNotFoundError,
    KnowledgeKeyTakenError,
)
from app.modules.knowledge.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


def _set_flags(entry: KnowledgeEntry, changes: Mapping[str, Any]) -> None:
    """Set the audience flags that were sent."""
    if "accessible_to_guest" in changes:
        entry.accessible_to_guest = bool(changes["accessible_to_guest"])
    if "accessible_to_student" in changes:
        entry.accessible_to_student = bool(changes["accessible_to_student"])


class UpdateEntry:
    """Apply the sent fields and re-embed the entry when its text changed."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, indexer: EntryIndexer
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._indexer = indexer

    async def execute(
        self, entry_id: UUID, changes: Mapping[str, Any]
    ) -> KnowledgeEntry:
        """Change `key`, `title`, `value` and `tags` (only the keys present)."""
        async with self._uow_factory() as uow:
            entry = await uow.entries.get(entry_id)
            if entry is None:
                raise KnowledgeEntryNotFoundError()
            if "key" in changes:
                entry.key = normalize_key(changes["key"])
                other = await uow.entries.get_by_key(entry.key)
                if other is not None and other.id != entry.id:
                    raise KnowledgeKeyTakenError()
            if "value" in changes:
                entry.value = normalize_value(changes["value"])
            if "title" in changes:
                entry.title = normalize_title(changes["title"])
            if "tags" in changes:
                entry.tags = normalize_tags(list(changes["tags"] or []))
            _set_flags(entry, changes)
            entry.content_hash = text_hash(embed_text(entry))
            entry.updated_at = self._clock.now()
            await uow.entries.save(entry)
            await uow.commit()
        await self._indexer.index(entry)
        return entry
