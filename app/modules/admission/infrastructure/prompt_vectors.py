"""`PromptVectors` over the vectors module's `EmbeddingIndex`.

The index only embeds (`ensure`) and answers questions (`embed_query`); the vector of
a prompt is read back from the shared `vectors.embeddings` table by the sha256 of its
text and the model, like the student search does for its chunks.
"""

import hashlib
from collections.abc import Callable, Sequence

from app.modules.admission.ports.essay_flow import VectorSet
from app.shared.contracts.ai import AiProviderError
from app.shared.contracts.embeddings import EmbeddingIndex, QueryVector, TextToEmbed
from app.shared.db.embeddings import Embedding

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class EmbeddingPromptVectors:
    """Vectors of public prompt texts and of one student's text."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        embeddings: Callable[[], EmbeddingIndex | None],
    ) -> None:
        """The index is read on each use: the composition root builds it later."""
        self._sm = sessionmaker
        self._index = embeddings

    async def of_texts(self, texts: Sequence[str]) -> VectorSet | None:
        """Vectors of public texts; None when no model answers or one is missing."""
        index = self._index()
        if index is None or not texts:
            return None
        hashes = [_hash(t) for t in texts]
        try:
            await index.ensure(
                [TextToEmbed(h, t) for h, t in dict(zip(hashes, texts)).items()]
            )
        except AiProviderError:
            return None
        async with self._sm() as session:
            rows = await session.execute(
                select(Embedding.content_hash, Embedding.embedding).where(
                    Embedding.model == index.model,
                    Embedding.content_hash.in_(set(hashes)),
                )
            )
            found = dict(rows.tuples().all())
        if any(h not in found for h in hashes):
            return None
        return VectorSet(index.model, [list(found[h]) for h in hashes])

    async def of_query(self, text: str) -> QueryVector | None:
        """The vector of a student's text; None when unavailable."""
        index = self._index()
        return None if index is None else await index.embed_query(text)
