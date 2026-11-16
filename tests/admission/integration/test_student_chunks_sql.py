"""The chunk store on PostgreSQL: words index, pgvector join, student isolation."""

from datetime import UTC, datetime
from uuid import UUID

from app.modules.admission.domain.student_chunks import make_chunks
from app.modules.admission.infrastructure.student_chunks_repository import (
    SqlChunkCollector,
    SqlChunkStore,
)
from app.modules.vectors.infrastructure.sql_embedding_store import SqlEmbeddingStore
from app.shared.db.embeddings import EMBEDDING_DIMS

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

A = UUID("00000000-0000-0000-0000-00000000000a")
B = UUID("00000000-0000-0000-0000-00000000000b")
NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
MODEL = "test/model"


def unit(index: int) -> list[float]:
    values = [0.0] * EMBEDDING_DIMS
    values[index] = 1.0
    return values


@pytest.fixture
def store(sessionmaker_in_tx: async_sessionmaker[AsyncSession]) -> SqlChunkStore:
    return SqlChunkStore(sessionmaker_in_tx)


async def test_replace_text_search_and_isolation(store: SqlChunkStore) -> None:
    mine = [
        *make_chunks("item", "i1", "Robotics club", "Led a robotics team"),
        *make_chunks("task", "t1", "Visa", "Book the embassy appointment"),
    ]
    theirs = make_chunks("item", "b1", "Robotics", "Another robotics team")
    assert await store.replace(A, mine, NOW) == 2
    await store.replace(B, theirs, NOW)
    found = await store.text_search(A, ["robot"], (), 10)
    assert [(c.source, c.ref_id) for c in found] == [("item", "i1")]
    assert await store.text_search(A, ["robot"], ("task",), 10) == []
    assert await store.indexed_at(A) == NOW
    assert await store.replace(A, mine[:1], NOW) == 1
    assert len(await store.text_search(A, ["visa"], (), 10)) == 0
    await store.delete(A)
    assert await store.text_search(A, ["robot"], (), 10) == []
    assert await store.indexed_at(A) is None
    assert len(await store.text_search(B, ["robot"], (), 10)) == 1


async def test_empty_student_is_stamped_but_never_found(store: SqlChunkStore) -> None:
    assert await store.replace(A, [], NOW) == 0
    assert await store.indexed_at(A) == NOW
    assert await store.text_search(A, ["marker"], (), 10) == []


async def test_vector_search_joins_embeddings_of_the_model(
    store: SqlChunkStore, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    near = make_chunks("item", "i1", "Near", "close")[0]
    far = make_chunks("item", "i2", "Far", "away")[0]
    other = make_chunks("item", "b1", "Other", "another student")[0]
    await store.replace(A, [near, far], NOW)
    await store.replace(B, [other], NOW)
    await SqlEmbeddingStore(sessionmaker_in_tx).put(
        MODEL,
        [
            (near.content_hash, unit(0)),
            (far.content_hash, unit(5)),
            (other.content_hash, unit(0)),
        ],
    )
    hits = await store.vector_search(A, MODEL, unit(0), (), 10)
    assert [c.ref_id for c in hits] == ["i1"]  # i2 is orthogonal: too far
    assert await store.vector_search(A, "other/model", unit(0), (), 10) == []
    assert await store.vector_search(A, MODEL, [1.0, 0.0], (), 10) == []


async def test_collector_of_an_unknown_student_is_empty(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    collector = SqlChunkCollector(sessionmaker_in_tx)
    assert await collector.collect(A) == []
    assert await collector.latest_change(A) is None
