"""Create a knowledge entry (administrator)."""

from collections.abc import Sequence
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
from app.modules.knowledge.domain.errors import KnowledgeKeyTakenError
from app.modules.knowledge.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.ids import new_id


class CreateEntry:
    """Validate, store and embed a new entry."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, indexer: EntryIndexer
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._indexer = indexer

    async def execute(
        self,
        author_id: UUID,
        *,
        key: str,
        value: str,
        title: str | None = None,
        tags: Sequence[str] = (),
    ) -> KnowledgeEntry:
        """Create the entry.

        Raises:
            KnowledgeInvalidError: A field is empty or too long.
            KnowledgeKeyTakenError: Another entry has this key (any case).
        """
        now = self._clock.now()
        entry = KnowledgeEntry(
            id=new_id(),
            key=normalize_key(key),
            value=normalize_value(value),
            title=normalize_title(title),
            tags=normalize_tags(list(tags)),
            author_id=author_id,
            created_at=now,
            updated_at=now,
        )
        entry.content_hash = text_hash(embed_text(entry))
        async with self._uow_factory() as uow:
            if await uow.entries.get_by_key(entry.key) is not None:
                raise KnowledgeKeyTakenError()
            await uow.entries.add(entry)
            await uow.commit()
        await self._indexer.index(entry)
        return entry
