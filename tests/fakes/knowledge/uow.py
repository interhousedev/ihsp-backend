"""In-memory unit of work of the knowledge module (copies in and out)."""

import copy
import re
from collections.abc import Callable, Sequence
from difflib import SequenceMatcher
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.knowledge.domain.entry import (
    KnowledgeEntry,
    LexicalHit,
    SemanticHit,
    visible_to,
)
from app.shared.contracts.embeddings import QueryVector
from app.shared.contracts.school_knowledge import Audience

WORD = re.compile(r"[^\W_]+", re.UNICODE)


class FakeKnowledgeStore:
    """The "database": entries, and the vectors of `vectors.embeddings` by
    (model, content hash), shared by every unit of work."""

    def __init__(self) -> None:
        """Start empty; `vectors` is the dict of a FakeEmbeddingStore."""
        self.entries: dict[UUID, KnowledgeEntry] = {}
        self.vectors: dict[tuple[str, str], list[float]] = {}
        self.commits = 0


def _has_tags(entry: KnowledgeEntry, tags: Sequence[str]) -> bool:
    return all(tag in entry.tags for tag in tags)


class FakeEntryRepository:
    """Entries of a FakeKnowledgeStore; word search approximates pg_trgm."""

    def __init__(self, store: FakeKnowledgeStore) -> None:
        """Bind to the store."""
        self.store = store

    async def get(self, entry_id: UUID) -> KnowledgeEntry | None:
        """Return a copy of the entry."""
        found = self.store.entries.get(entry_id)
        return copy.deepcopy(found) if found else None

    async def get_by_key(self, key: str) -> KnowledgeEntry | None:
        """Return the entry with this key."""
        for entry in self.store.entries.values():
            if entry.key == key:
                return copy.deepcopy(entry)
        return None

    async def add(self, entry: KnowledgeEntry) -> None:
        """Insert an entry."""
        self.store.entries[entry.id] = copy.deepcopy(entry)

    async def save(self, entry: KnowledgeEntry) -> None:
        """Store the entry's fields."""
        self.store.entries[entry.id] = copy.deepcopy(entry)

    async def delete(self, entry_id: UUID) -> None:
        """Delete the entry."""
        self.store.entries.pop(entry_id, None)

    async def list_page(
        self, tags: Sequence[str], limit: int, offset: int
    ) -> tuple[list[KnowledgeEntry], int]:
        """Entries with all the tags, newest change first."""
        found = [e for e in self.store.entries.values() if _has_tags(e, tags)]
        found.sort(key=lambda e: (e.updated_at, str(e.id)), reverse=True)
        return copy.deepcopy(found[offset : offset + limit]), len(found)

    async def search_lexical(
        self,
        query: str,
        min_similarity: float,
        tags: Sequence[str],
        limit: int,
        audience: Audience,
    ) -> list[LexicalHit]:
        """Entries sharing a word prefix with the query, or similar to it."""
        words = [w for w in WORD.findall(query.lower()) if len(w) >= 3]
        hits: list[LexicalHit] = []
        for entry in self.store.entries.values():
            if not _has_tags(entry, tags) or not visible_to(entry, audience):
                continue
            text = f"{entry.key} {entry.title or ''} {entry.value}".lower()
            tokens = WORD.findall(text)
            matched = sum(any(t.startswith(w) for t in tokens) for w in words)
            similarity = SequenceMatcher(None, query.lower(), entry.key).ratio()
            if matched or similarity >= min_similarity:
                hits.append(LexicalHit(copy.deepcopy(entry), similarity, matched))
        hits.sort(key=lambda h: (-h.rank, -h.similarity, h.entry.key))
        return hits[:limit]

    async def search_semantic(
        self,
        vector: QueryVector,
        tags: Sequence[str],
        limit: int,
        audience: Audience,
    ) -> list[SemanticHit]:
        """Entries with a vector of the model, by cosine similarity."""
        hits: list[SemanticHit] = []
        for entry in self.store.entries.values():
            values = self.store.vectors.get((vector.model, entry.content_hash or ""))
            if values is None or not _has_tags(entry, tags):
                continue
            if not visible_to(entry, audience):
                continue
            cosine = sum(a * b for a, b in zip(values, vector.values, strict=True))
            hits.append(SemanticHit(copy.deepcopy(entry), cosine))
        hits.sort(key=lambda h: (-h.similarity, h.entry.key))
        return hits[:limit]


class FakeKnowledgeUnitOfWork:
    """Opens on entry; commit() counts."""

    def __init__(self, store: FakeKnowledgeStore) -> None:
        """Bind to the store."""
        self.store = store
        self.entries = FakeEntryRepository(store)

    async def __aenter__(self) -> Self:
        """Open."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Nothing to roll back: the fake writes at once."""

    async def commit(self) -> None:
        """Count the commit."""
        self.store.commits += 1


def fake_uow_factory(
    store: FakeKnowledgeStore,
) -> Callable[[], FakeKnowledgeUnitOfWork]:
    """A factory of units of work over the store."""
    return lambda: FakeKnowledgeUnitOfWork(store)
