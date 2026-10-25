"""Hybrid search: meaning (vectors) and words (trigrams, full text), fused by rank."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.knowledge.application.entry_indexer import EmbeddingsProvider
from app.modules.knowledge.domain.entry import KnowledgeEntry
from app.modules.knowledge.ports.unit_of_work import UowFactory
from app.settings import KnowledgeSettings
from app.shared.contracts.school_knowledge import Audience
from app.shared.rank_fusion import RRF_K, reciprocal_rank_fusion

MAX_QUERY_CHARS = 500


@dataclass(frozen=True, slots=True)
class ScoredEntry:
    """An entry and its fused score."""

    entry: KnowledgeEntry
    score: float


class SearchEntries:
    """Vector top-N plus word top-N, merged with reciprocal rank fusion (k=60).

    A vector hit counts when its cosine similarity reaches `vector_min_similarity`; a
    word hit when its trigram similarity reaches `trigram_min_similarity` or its
    words match the full-text index. Anything weaker is dropped before the merge.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        embeddings: EmbeddingsProvider,
        settings: KnowledgeSettings,
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._embeddings = embeddings
        self._settings = settings

    async def execute(
        self,
        query: str,
        *,
        limit: int,
        audience: Audience,
        tags: Sequence[str] = (),
    ) -> list[ScoredEntry]:
        """Up to `limit` entries visible to the audience, best first.

        Empty for an empty query.
        """
        text = " ".join(query.split())[:MAX_QUERY_CHARS]
        if not text or limit < 1:
            return []
        wanted = max(self._settings.candidates, limit)
        by_id: dict[UUID, KnowledgeEntry] = {}
        semantic_ids: list[UUID] = []
        index = self._embeddings()
        vector = await index.embed_query(text) if index is not None else None
        async with self._uow_factory() as uow:
            if vector is not None:
                for hit in await uow.entries.search_semantic(
                    vector, tags, wanted, audience
                ):
                    if hit.similarity >= self._settings.vector_min_similarity:
                        by_id[hit.entry.id] = hit.entry
                        semantic_ids.append(hit.entry.id)
            lexical = await uow.entries.search_lexical(
                text, self._settings.trigram_min_similarity, tags, wanted, audience
            )
        lexical_ids = [found.entry.id for found in lexical]
        by_id.update({found.entry.id: found.entry for found in lexical})
        order = reciprocal_rank_fusion([semantic_ids, lexical_ids])[:limit]
        return [
            ScoredEntry(by_id[i], fused_score(i, semantic_ids, lexical_ids))
            for i in order
        ]


def fused_score(item: UUID, *rankings: list[UUID]) -> float:
    """The fused score of an item: the sum of `1 / (k + rank)` over the rankings."""
    return sum(
        1.0 / (RRF_K + ranking.index(item) + 1)
        for ranking in rankings
        if item in ranking
    )
