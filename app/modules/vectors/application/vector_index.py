"""`EmbeddingIndex`: the public API of the vectors module."""

from collections.abc import Sequence

from app.modules.vectors.application.embed_query import EmbedQuery
from app.modules.vectors.application.embed_texts import EmbedTexts
from app.shared.contracts.embeddings import (
    EmbeddingGateway,
    EmbedReport,
    QueryVector,
    TextToEmbed,
)


class VectorIndex:
    """Implements `app.shared.contracts.embeddings.EmbeddingIndex`."""

    def __init__(
        self, gateway: EmbeddingGateway, texts: EmbedTexts, query: EmbedQuery
    ) -> None:
        """Combine the two use cases behind one object."""
        self.gateway = gateway
        self._texts = texts
        self._query = query

    @property
    def model(self) -> str:
        """The model id of the vectors."""
        return self.gateway.model

    async def ensure(self, texts: Sequence[TextToEmbed]) -> EmbedReport:
        """Give every distinct text a vector."""
        return await self._texts.execute(texts)

    async def embed_query(self, text: str) -> QueryVector | None:
        """The vector of a question, or None when it cannot be had in time."""
        return await self._query.execute(text)
