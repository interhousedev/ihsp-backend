"""NB-14: `vectors.embeddings` in PostgreSQL with pgvector (`halfvec`, cosine)."""

from app.modules.vectors.infrastructure.sql_embedding_store import SqlEmbeddingStore
from app.shared.db.embeddings import EMBEDDING_DIMS

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

MODEL = "test/model"
A, B, C = "a" * 64, "b" * 64, "c" * 64


def unit(index: int, *, other: int | None = None) -> list[float]:
    """A vector with a 1 at `index` (and a 1 at `other`), the rest zeros."""
    values = [0.0] * EMBEDDING_DIMS
    values[index] = 1.0
    if other is not None:
        values[other] = 1.0
    return values


@pytest.fixture
def store(sessionmaker_in_tx: async_sessionmaker[AsyncSession]) -> SqlEmbeddingStore:
    """The store over the test transaction."""
    return SqlEmbeddingStore(sessionmaker_in_tx)


async def test_a_stored_vector_is_found_by_hash_and_model(
    store: SqlEmbeddingStore,
) -> None:
    """`existing` answers per model."""
    added = await store.put(MODEL, [(A, unit(0)), (B, unit(1))])

    assert added == 2
    assert await store.existing([A, B, C], MODEL) == {A, B}
    assert await store.existing([A], "another/model") == set()
    assert await store.existing([], MODEL) == set()


async def test_putting_a_hash_again_keeps_the_first_vector(
    store: SqlEmbeddingStore, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """Two jobs embedding the same text do not overwrite each other."""
    await store.put(MODEL, [(A, unit(0))])

    added = await store.put(MODEL, [(A, unit(5)), (B, unit(1))])

    assert added == 1
    async with sessionmaker_in_tx() as session:
        first = (
            await session.execute(
                text(
                    "SELECT (embedding::real[])[1] FROM vectors.embeddings "
                    "WHERE content_hash = :h"
                ),
                {"h": A},
            )
        ).scalar_one()
    assert first == 1.0


async def test_one_text_can_have_vectors_of_several_models(
    store: SqlEmbeddingStore,
) -> None:
    """The key is (hash, model): a model change re-embeds next to the old rows."""
    await store.put("model/one", [(A, unit(0))])
    await store.put("model/two", [(A, unit(1))])

    assert await store.existing([A], "model/one") == {A}
    assert await store.existing([A], "model/two") == {A}


async def test_cosine_distance_orders_by_direction_not_length(
    store: SqlEmbeddingStore, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """`<=>` on halfvec: the nearest direction first."""
    await store.put(MODEL, [(A, unit(0)), (B, unit(1)), (C, unit(0, other=1))])
    query = "[" + ",".join(str(v) for v in unit(0)) + "]"

    async with sessionmaker_in_tx() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT content_hash FROM vectors.embeddings WHERE model = :m "
                    "ORDER BY embedding <=> CAST(:q AS halfvec(1024))"
                ),
                {"m": MODEL, "q": query},
            )
        ).scalars()
        order = [row.strip() for row in rows]

    assert order == [A, C, B]


async def test_the_stored_size_must_be_the_column_size(
    store: SqlEmbeddingStore,
) -> None:
    """A vector of another size cannot be stored (the column is halfvec(1024))."""
    with pytest.raises(DBAPIError):
        await store.put(MODEL, [(A, [1.0, 2.0, 3.0])])


async def test_the_dimension_column_records_the_size(
    store: SqlEmbeddingStore, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """`dims` always equals `vector_dims(embedding)` (a check constraint)."""
    await store.put(MODEL, [(A, unit(0))])

    async with sessionmaker_in_tx() as session:
        dims = (
            await session.execute(
                text("SELECT dims, vector_dims(embedding) FROM vectors.embeddings")
            )
        ).one()

    assert tuple(dims) == (EMBEDDING_DIMS, EMBEDDING_DIMS)
