"""The vector of a question, cached, with a deadline."""

import asyncio
import hashlib

from app.modules.vectors.ports.query_cache import QueryCache
from app.modules.vectors.ports.token_budget import TokenBudget
from app.shared.contracts.ai import AiProviderError
from app.shared.contracts.embeddings import EmbeddingGateway, QueryVector

import structlog

log = structlog.get_logger(__name__)

MAX_QUERY_CHARS = 2_000  # a retrieval query is a question plus a previous message


def query_key(model: str, dims: int, text: str) -> str:
    """Cache key: the model, the size and the sha256 of the normalized question."""
    digest = hashlib.sha256(text.encode()).hexdigest()
    return f"vectors:q:{model}:{dims}:{digest}"


class EmbedQuery:
    """`EmbeddingIndex.embed_query`: never makes a chat turn wait or fail.

    The same question (after collapsing whitespace) is embedded once a day. A slow or
    failing provider yields None and the caller falls back to words, because a
    missing vector is a worse answer, not an error.
    """

    def __init__(
        self,
        *,
        gateway: EmbeddingGateway,
        cache: QueryCache,
        budget: TokenBudget,
        timeout_seconds: float,
        cache_seconds: int,
    ) -> None:
        """Store the collaborators and the deadline."""
        self.gateway = gateway
        self.cache = cache
        self.budget = budget
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = cache_seconds

    async def execute(self, text: str) -> QueryVector | None:
        """The vector of the question, or None when it cannot be had in time."""
        query = " ".join(text.split())[:MAX_QUERY_CHARS]
        if not query:
            return None
        model = self.gateway.model
        key = query_key(model, self.gateway.dims, query)
        cached = await self.cache.get(key)
        if cached is not None:
            return QueryVector(model, cached)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.gateway.embed([query], kind="query")
        except (TimeoutError, AiProviderError) as error:
            log.warning("vectors_query_unavailable", model=model, error=repr(error))
            return None
        values = result.vectors[0]
        await self.cache.put(key, values, self.cache_seconds)
        await self.budget.spend(result.tokens)
        return QueryVector(model, values)
