"""Builds the vectors module: the embedding index other modules call."""

from dataclasses import dataclass

from app.modules.vectors.application.embed_query import EmbedQuery
from app.modules.vectors.application.embed_texts import EmbedTexts
from app.modules.vectors.application.vector_index import VectorIndex
from app.modules.vectors.infrastructure.redis_query_cache import RedisQueryCache
from app.modules.vectors.infrastructure.redis_token_budget import RedisTokenBudget
from app.modules.vectors.infrastructure.sql_embedding_store import SqlEmbeddingStore
from app.shared.contracts.embeddings import EmbeddingGateway, EmbeddingIndex
from app.shared.wiring import ModuleDeps


@dataclass(frozen=True, slots=True)
class VectorsServices:
    """What the vectors module offers."""

    index: EmbeddingIndex


def build(deps: ModuleDeps, *, gateway: EmbeddingGateway) -> VectorsServices:
    """Wire the index over the embedding gateway, `vectors.embeddings` and Redis."""
    settings = deps.settings.vectors
    budget = RedisTokenBudget(deps.redis, deps.clock, settings.daily_token_budget)
    index = VectorIndex(
        gateway,
        EmbedTexts(
            gateway=gateway,
            store=SqlEmbeddingStore(deps.sessionmaker),
            budget=budget,
        ),
        EmbedQuery(
            gateway=gateway,
            cache=RedisQueryCache(deps.redis),
            budget=budget,
            timeout_seconds=settings.query_timeout_seconds,
            cache_seconds=settings.query_cache_seconds,
        ),
    )
    return VectorsServices(index=index)
