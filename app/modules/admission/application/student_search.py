"""`StudentDataSearch`: hybrid words plus meaning search over one student's data."""

from collections.abc import Callable, Sequence
from uuid import UUID

from app.modules.admission.domain.student_chunks import (
    Chunk,
    fuse,
    query_tokens,
    snippet,
    url_path,
)
from app.modules.admission.ports.student_chunks import ChunkCollector, ChunkStore
from app.modules.admission.ports.student_search import (
    StudentDataHit,
    StudentDataSource,
)
from app.shared.clock import Clock
from app.shared.contracts.ai import AiProviderError
from app.shared.contracts.embeddings import EmbeddingIndex, TextToEmbed

import structlog

log = structlog.get_logger(__name__)

_POOL = 4
"""Each ranking looks `limit * _POOL` deep before fusion."""
MAX_LIMIT = 50


class StudentSearchService:
    """Implements `StudentDataSearch`: full text and vectors fused by rank.

    The index is rebuilt on demand and lazily: a search first checks whether the
    student's data changed after the last indexing. The embedding index is read on
    each use because the composition root builds it after this module. Without it, or
    when the provider is down, only the word ranking answers.
    """

    def __init__(
        self,
        store: ChunkStore,
        collector: ChunkCollector,
        embeddings: Callable[[], EmbeddingIndex | None],
        clock: Clock,
    ) -> None:
        """Keep the collaborators."""
        self._store = store
        self._collector = collector
        self._index = embeddings
        self._clock = clock

    async def search(
        self,
        student_id: UUID,
        query: str,
        *,
        sources: tuple[StudentDataSource, ...] = (),
        limit: int = 8,
    ) -> list[StudentDataHit]:
        """Best hits first, only from this student's data."""
        tokens = query_tokens(query)
        limit = max(1, min(limit, MAX_LIMIT))
        if not tokens:
            return []
        await self._ensure_fresh(student_id)
        depth = limit * _POOL
        by_words = await self._store.text_search(student_id, tokens, sources, depth)
        by_meaning = await self._by_meaning(student_id, query, sources, depth)
        best: dict[tuple[str, str], Chunk] = {}
        for chunk in [*by_words, *by_meaning]:
            best.setdefault((chunk.source, chunk.ref_id), chunk)
        fused = fuse(
            [
                [(c.source, c.ref_id) for c in by_words],
                [(c.source, c.ref_id) for c in by_meaning],
            ]
        )
        return [
            StudentDataHit(
                source=best[key].source,
                ref_id=key[1],
                title=best[key].title,
                snippet=snippet(best[key].body),
                url_path=url_path(*key),
                score=score,
            )
            for key, score in fused[:limit]
        ]

    async def reindex(self, student_id: UUID) -> int:
        """Rebuild the student's chunks and their vectors."""
        chunks = await self._collector.collect(student_id)
        await self._embed(chunks)
        return await self._store.replace(student_id, chunks, self._clock.now())

    async def forget(self, student_id: UUID) -> None:
        """Drop the student's chunks."""
        await self._store.delete(student_id)

    async def _ensure_fresh(self, student_id: UUID) -> None:
        """Rebuild when never indexed, newer data exists, or the row count differs."""
        latest = await self._collector.latest_change(student_id)
        wanted = await self._collector.ref_count(student_id)
        have = await self._store.ref_count(student_id)
        if latest is None and wanted == 0:
            if have:
                await self.reindex(student_id)
            return
        indexed = await self._store.indexed_at(student_id)
        if indexed is None or wanted != have or (latest and latest > indexed):
            await self.reindex(student_id)

    async def _embed(self, chunks: Sequence[Chunk]) -> None:
        index = self._index()
        if index is None or not chunks:
            return
        try:
            await index.ensure(
                [TextToEmbed(c.content_hash, c.embed_text) for c in chunks]
            )
        except AiProviderError as error:
            log.warning("admission_student_embed_failed", error=repr(error))

    async def _by_meaning(
        self,
        student_id: UUID,
        query: str,
        sources: Sequence[StudentDataSource],
        depth: int,
    ) -> list[Chunk]:
        index = self._index()
        if index is None:
            return []
        vector = await index.embed_query(query)
        if vector is None:
            return []
        return await self._store.vector_search(
            student_id, vector.model, vector.values, sources, depth
        )
