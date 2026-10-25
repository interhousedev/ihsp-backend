"""vectors_0001: pgvector, the shared embeddings table and its HNSW index."""

import asyncio

from app.shared.db import models  # noqa: F401  (imports every module's ORM package)
from app.shared.db.base import Base
from tests.models.conftest import DatabaseFactory, run_alembic

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine


async def _alembic(url: str, *args: str) -> None:
    await asyncio.to_thread(run_alembic, url, *args)


async def _scalar(url: str, sql: str) -> object:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql))).scalar()
    finally:
        await engine.dispose()


def _vectors_differences(connection: Connection) -> list[object]:
    """What autogenerate sees between the vectors schema and the models."""
    context = MigrationContext.configure(
        connection,
        opts={
            "include_schemas": True,
            "include_name": lambda name, type_, parents: (
                name == "vectors" if type_ == "schema" else True
            ),
            "include_object": lambda obj, name, type_, reflected, compare_to: (
                getattr(obj, "schema", None) == "vectors"
                or getattr(getattr(obj, "table", None), "schema", None) == "vectors"
            ),
            "compare_type": True,
            "version_table_schema": "public",
        },
    )
    return list(compare_metadata(context, Base.metadata))


async def test_vectors_branch_stands_alone_and_matches_the_model(
    new_database: DatabaseFactory,
) -> None:
    """NB-14: `vectors@head` alone makes the extension, the table and the index."""
    url = await new_database()

    await _alembic(url, "upgrade", "vectors@head")

    assert (
        await _scalar(url, "SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
        == 1
    )
    assert (
        await _scalar(
            url,
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'vectors.embeddings'::regclass AND attname = 'embedding'",
        )
        == "halfvec(1024)"
    )
    index = await _scalar(
        url,
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'vectors' "
        "AND indexname = 'ix_embeddings_embedding_hnsw'",
    )
    assert isinstance(index, str)
    assert "USING hnsw" in index and "halfvec_cosine_ops" in index
    assert "m='16'" in index and "ef_construction='64'" in index
    assert (
        await _scalar(
            url,
            "SELECT attstorage::text FROM pg_attribute WHERE attrelid = "
            "'vectors.embeddings'::regclass AND attname = 'embedding'",
        )
        == "p"
    )
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            assert await conn.run_sync(_vectors_differences) == []
    finally:
        await engine.dispose()


async def test_the_table_keeps_one_vector_per_text_and_model_and_checks_the_size(
    new_database: DatabaseFactory,
) -> None:
    """NB-14: primary key (content_hash, model); a vector of 1024 numbers only."""
    url = await new_database()
    await _alembic(url, "upgrade", "vectors@head")
    vector = "[" + ",".join(["0.5"] * 1024) + "]"
    insert = text(
        "INSERT INTO vectors.embeddings (content_hash, model, dims, embedding) "
        "VALUES (:h, :m, :d, CAST(:v AS halfvec(1024)))"
    )
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                insert, {"h": "a" * 64, "m": "m1", "d": 1024, "v": vector}
            )
            await conn.execute(
                insert, {"h": "a" * 64, "m": "m2", "d": 1024, "v": vector}
            )
        with pytest.raises(DBAPIError):  # the same text and model again
            async with engine.begin() as conn:
                await conn.execute(
                    insert, {"h": "a" * 64, "m": "m1", "d": 1024, "v": vector}
                )
        with pytest.raises(DBAPIError):  # `dims` must tell the truth
            async with engine.begin() as conn:
                await conn.execute(
                    insert, {"h": "b" * 64, "m": "m1", "d": 512, "v": vector}
                )
        async with engine.connect() as conn:
            nearest = (
                await conn.execute(
                    text(
                        "SELECT model FROM vectors.embeddings "
                        "ORDER BY embedding <=> CAST(:v AS halfvec(1024)), model "
                        "LIMIT 1"
                    ),
                    {"v": vector},
                )
            ).scalar()
    finally:
        await engine.dispose()
    assert nearest == "m1"


async def test_downgrade_removes_the_schema_and_keeps_the_extension(
    new_database: DatabaseFactory,
) -> None:
    """Going back drops the table and the schema; `vector` may serve others later."""
    url = await new_database()
    await _alembic(url, "upgrade", "vectors@head")

    await _alembic(url, "downgrade", "vectors@base")

    assert (
        await _scalar(
            url, "SELECT count(*) FROM pg_namespace WHERE nspname = 'vectors'"
        )
        == 0
    )
    assert (
        await _scalar(url, "SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
        == 1
    )
    await _alembic(url, "upgrade", "vectors@head")
    assert await _scalar(url, "SELECT count(*) FROM vectors.embeddings") == 0
