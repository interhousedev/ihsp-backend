"""A real `VectorIndex` over the test database and the fake embedding model."""

from app.modules.ai.infrastructure.fake_embeddings import FakeEmbeddingGateway
from app.modules.vectors.application.embed_query import EmbedQuery
from app.modules.vectors.application.embed_texts import EmbedTexts
from app.modules.vectors.application.vector_index import VectorIndex
from app.modules.vectors.infrastructure.sql_embedding_store import SqlEmbeddingStore
from tests.fakes.vectors.stores import FakeQueryCache, FakeTokenBudget

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def make_index(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    gateway: FakeEmbeddingGateway | None = None,
    budget: FakeTokenBudget | None = None,
) -> tuple[VectorIndex, FakeEmbeddingGateway]:
    """The index (SQL store, fake cache and budget) and the gateway it embeds with."""
    gateway = gateway or FakeEmbeddingGateway()
    budget = budget or FakeTokenBudget()
    index = VectorIndex(
        gateway,
        EmbedTexts(
            gateway=gateway, store=SqlEmbeddingStore(sessionmaker), budget=budget
        ),
        EmbedQuery(
            gateway=gateway,
            cache=FakeQueryCache(),
            budget=budget,
            timeout_seconds=2.0,
            cache_seconds=60,
        ),
    )
    return index, gateway
