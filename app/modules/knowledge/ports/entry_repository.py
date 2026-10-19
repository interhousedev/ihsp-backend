"""Port: storage and lookup of knowledge entries."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.knowledge.domain.entry import (
    KnowledgeEntry,
    LexicalHit,
    SemanticHit,
)
from app.shared.contracts.embeddings import QueryVector


class EntryRepository(Protocol):
    """Entries of `knowledge.entries`."""

    async def get(self, entry_id: UUID) -> KnowledgeEntry | None:
        """Return the entry or None."""
        ...

    async def get_by_key(self, key: str) -> KnowledgeEntry | None:
        """Return the entry with this (normalized) key or None."""
        ...

    async def add(self, entry: KnowledgeEntry) -> None:
        """Insert an entry."""
        ...

    async def save(self, entry: KnowledgeEntry) -> None:
        """Write the entry's fields."""
        ...

    async def delete(self, entry_id: UUID) -> None:
        """Delete the entry."""
        ...

    async def list_page(
        self, tags: Sequence[str], limit: int, offset: int
    ) -> tuple[list[KnowledgeEntry], int]:
        """Entries that carry all `tags`, newest change first, and the total."""
        ...

    async def search_lexical(
        self, query: str, min_similarity: float, tags: Sequence[str], limit: int
    ) -> list[LexicalHit]:
        """Entries whose key, title or value is similar to the query or has its words.

        Best first (full-text rank, then trigram similarity).
        """
        ...

    async def search_semantic(
        self, vector: QueryVector, tags: Sequence[str], limit: int
    ) -> list[SemanticHit]:
        """Entries with a vector of the query's model, nearest first."""
        ...
