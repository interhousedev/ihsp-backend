"""notebooks_0002: schema agrees with the models; existing passages are converted."""

import asyncio
import hashlib

from app.shared.db import models  # noqa: F401  (imports every module's ORM package)
from app.shared.db.base import Base
from tests.models.conftest import DatabaseFactory, run_alembic

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine


async def _alembic(url: str, *args: str) -> None:
    await asyncio.to_thread(run_alembic, url, *args)


def _notebooks_differences(connection: Connection) -> list[object]:
    """What Alembic autogenerate sees between the notebooks schema and the models."""
    context = MigrationContext.configure(
        connection,
        opts={
            "include_schemas": True,
            "include_name": lambda name, type_, parents: (
                name == "notebooks" if type_ == "schema" else True
            ),
            "include_object": lambda obj, name, type_, reflected, compare_to: (
                getattr(obj, "schema", None) == "notebooks"
                or getattr(getattr(obj, "table", None), "schema", None) == "notebooks"
            ),
            "compare_type": True,
            "version_table_schema": "public",
        },
    )
    return list(compare_metadata(context, Base.metadata))


async def test_notebooks_head_matches_the_models_including_passage_hash(
    new_database: DatabaseFactory,
) -> None:
    """NB-14: columns and indexes of the notebooks schema are what the models say."""
    url = await new_database()
    await _alembic(url, "upgrade", "notebooks@head")

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            differences = await conn.run_sync(_notebooks_differences)
    finally:
        await engine.dispose()

    assert differences == []


async def test_existing_passages_get_the_hash_of_their_text_and_the_revision_reverts(
    new_database: DatabaseFactory,
) -> None:
    """NB-14: 0002 fills `content_hash` in SQL like `passage_hash`; 0001 gets back."""
    url = await new_database()
    await _alembic(url, "upgrade", "notebooks_0001")
    notebook_id, source_id = (
        "0198f000-0000-7000-8000-000000000001",
        "0198f000-0000-7000-8000-000000000002",
    )
    body = "Фотосинтез: растения используют свет."
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO notebooks.notebooks (id, owner_id, title) "
                    "VALUES (:n, gen_random_uuid(), 'T')"
                ),
                {"n": notebook_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO notebooks.sources (id, notebook_id, owner_id, kind, "
                    "title, position, status, content_hash, passage_count) "
                    "VALUES (:s, :n, gen_random_uuid(), 'text', 'S', 1, 'ready', "
                    ":h, 1)"
                ),
                {"s": source_id, "n": notebook_id, "h": "b" * 64},
            )
            await conn.execute(
                text(
                    "INSERT INTO notebooks.passages (id, source_id, notebook_id, seq, "
                    "text, char_start, char_end, token_estimate) "
                    "VALUES (gen_random_uuid(), :s, :n, 1, :t, 0, :e, 9)"
                ),
                {"s": source_id, "n": notebook_id, "t": body, "e": len(body)},
            )
    finally:
        await engine.dispose()

    await _alembic(url, "upgrade", "notebooks@head")

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            stored = (
                (
                    await conn.execute(
                        text("SELECT content_hash FROM notebooks.passages")
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()
    assert stored == [hashlib.sha256(body.encode()).hexdigest()]

    await _alembic(url, "downgrade", "notebooks_0001")

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            columns = (
                (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns WHERE "
                            "table_schema = 'notebooks' AND table_name = 'passages'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            kept = (
                await conn.execute(text("SELECT count(*) FROM notebooks.passages"))
            ).scalar()
    finally:
        await engine.dispose()
    assert "content_hash" not in columns and "source_id" in columns and kept == 1
