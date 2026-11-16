"""In-memory chunk store and collector under `StudentSearchService`."""

import math
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.admission.domain.student_chunks import MAX_VECTOR_DISTANCE, Chunk


class InMemoryChunkStore:
    """`ChunkStore`; `vectors` is the shared `content_hash` -> vector table."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        """Share the vector table with the fake embedding index."""
        self.vectors = vectors
        self.chunks: dict[UUID, list[Chunk]] = {}
        self.stamps: dict[UUID, datetime] = {}

    async def replace(
        self, student_id: UUID, chunks: Sequence[Chunk], now: datetime
    ) -> int:
        """Overwrite the student's chunks."""
        self.chunks[student_id] = list(chunks)
        self.stamps[student_id] = now
        return len(chunks)

    async def delete(self, student_id: UUID) -> None:
        """Drop the student's chunks and the vectors no other student uses."""
        gone = {c.content_hash for c in self.chunks.pop(student_id, [])}
        kept = {c.content_hash for rows in self.chunks.values() for c in rows}
        for key in gone - kept:
            self.vectors.pop(key, None)
        self.stamps.pop(student_id, None)

    async def ref_count(self, student_id: UUID) -> int:
        """Distinct rows indexed."""
        return len({(c.source, c.ref_id) for c in self.chunks.get(student_id, [])})

    async def indexed_at(self, student_id: UUID) -> datetime | None:
        """The last indexing time."""
        return self.stamps.get(student_id)

    async def text_search(
        self,
        student_id: UUID,
        tokens: Sequence[str],
        sources: Sequence[str],
        limit: int,
    ) -> list[Chunk]:
        """Chunks by the number of matching token prefixes."""
        scored = []
        for chunk in self._of(student_id, sources):
            words = chunk.embed_text.casefold().split()
            hits = sum(any(w.startswith(t) for w in words) for t in tokens)
            if hits:
                scored.append((-hits, chunk))
        scored.sort(key=lambda p: p[0])
        return [c for _, c in scored][:limit]

    async def vector_search(
        self,
        student_id: UUID,
        model: str,
        vector: Sequence[float],
        sources: Sequence[str],
        limit: int,
    ) -> list[Chunk]:
        """Chunks by cosine similarity."""
        scored = [
            (_dot(self.vectors[c.content_hash], vector), c)
            for c in self._of(student_id, sources)
            if c.content_hash in self.vectors
        ]
        scored = [(d, c) for d, c in scored if 1 - d < MAX_VECTOR_DISTANCE]
        scored.sort(key=lambda p: -p[0])
        return [c for _, c in scored][:limit]

    def _of(self, student_id: UUID, sources: Sequence[str]) -> list[Chunk]:
        return [
            c
            for c in self.chunks.get(student_id, [])
            if not sources or c.source in sources
        ]


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return math.fsum(x * y for x, y in zip(a, b, strict=False))


class FakeChunkCollector:
    """`ChunkCollector` over a dict of chunks per student."""

    def __init__(self) -> None:
        """Start without data."""
        self.data: dict[UUID, list[Chunk]] = {}
        self.changed: dict[UUID, datetime] = {}
        self.collects = 0

    def put(self, student_id: UUID, chunks: list[Chunk], at: datetime) -> None:
        """Set the student's data and its change time."""
        self.data[student_id] = chunks
        self.changed[student_id] = at

    async def collect(self, student_id: UUID) -> list[Chunk]:
        """The student's chunks."""
        self.collects += 1
        return list(self.data.get(student_id, []))

    async def ref_count(self, student_id: UUID) -> int:
        """Distinct rows of the data."""
        return len({(c.source, c.ref_id) for c in self.data.get(student_id, [])})

    async def latest_change(self, student_id: UUID) -> datetime | None:
        """The change time."""
        return self.changed.get(student_id)
