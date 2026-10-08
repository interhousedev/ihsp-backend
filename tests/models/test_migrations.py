"""Migrations: upgrade, downgrade, upgrade again, and agreement with the models.

Each ``alembic`` run is a subprocess (about as slow as a real deployment step), so
the tests are few and each walks through a whole scenario.
"""

import asyncio

from app.shared.db import models  # noqa: F401  (imports every module's ORM package)
from app.shared.db.base import Base
from tests.models.conftest import DatabaseFactory, run_alembic

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

SCHEMAS = {"id", "academic", "files", "links", "ai", "notify", "admin", "mail", "lms"}
AI_TABLES = {"ai.chats", "ai.chat_messages"}
FLASHCARD_TABLES = {"ai.flashcard_sets", "ai.flashcards", "ai.flashcard_reviews"}


def _model_tables() -> set[str]:
    """Return ``schema.table`` of every table of the ORM models."""
    return {table.fullname for table in Base.metadata.tables.values()}


async def _tables(url: str) -> set[str]:
    """Return ``schema.table`` of every table in the module schemas."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT schemaname || '.' || tablename FROM pg_tables "
                    "WHERE schemaname = ANY(:schemas)"
                ),
                {"schemas": sorted(SCHEMAS)},
            )
            return {row[0] for row in rows}
    finally:
        await engine.dispose()


async def _scalar(url: str, sql: str) -> object:
    """Run one query and return its first value."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql))).scalar()
    finally:
        await engine.dispose()


async def _alembic(url: str, *args: str) -> None:
    """Run alembic without blocking the event loop."""
    await asyncio.to_thread(run_alembic, url, *args)


def _compare(connection: Connection) -> list[object]:
    """Return the differences Alembic autogenerate sees between DB and models."""
    context = MigrationContext.configure(
        connection,
        opts={
            "include_schemas": True,
            "include_name": lambda name, type_, parents: (
                name in SCHEMAS if type_ == "schema" else True
            ),
            "compare_type": True,
            "version_table_schema": "public",
        },
    )
    return list(compare_metadata(context, Base.metadata))


async def test_upgrade_heads_builds_exactly_the_models(
    new_database: DatabaseFactory,
) -> None:
    """On an empty database one ``upgrade heads`` creates the 34 tables of the
    models, with no difference left for autogenerate, and btree_gist."""
    url = await new_database()

    await _alembic(url, "upgrade", "heads")

    assert await _tables(url) == _model_tables()
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            assert await conn.run_sync(_compare) == []
    finally:
        await engine.dispose()
    assert (
        await _scalar(
            url, "SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'"
        )
        == 1
    )


async def test_downgrade_base_then_upgrade_heads_again(
    new_database: DatabaseFactory,
) -> None:
    """Upgrade -> downgrade of every branch -> upgrade leaves a complete database."""
    url = await new_database()

    await _alembic(url, "upgrade", "heads")
    await _alembic(url, "downgrade", "base")
    assert await _tables(url) == set()
    assert (
        await _scalar(
            url,
            "SELECT count(*) FROM pg_namespace WHERE nspname = ANY(ARRAY["
            + ",".join(f"'{schema}'" for schema in sorted(SCHEMAS))
            + "])",
        )
        == 0
    )
    await _alembic(url, "upgrade", "heads")

    assert await _tables(url) == _model_tables()


async def test_ai_and_flashcards_branches_share_schema_ai_in_any_order(
    new_database: DatabaseFactory,
) -> None:
    """flashcards can be created before ai; each can be removed without the other."""
    url = await new_database()

    await _alembic(url, "upgrade", "flashcards@head")
    assert await _tables(url) == FLASHCARD_TABLES
    await _alembic(url, "upgrade", "heads")
    assert await _tables(url) == _model_tables()

    await _alembic(url, "downgrade", "ai@base")
    tables = await _tables(url)
    assert FLASHCARD_TABLES <= tables
    assert not AI_TABLES & tables

    await _alembic(url, "upgrade", "heads")
    await _alembic(url, "downgrade", "flashcards@base")
    tables = await _tables(url)
    assert AI_TABLES <= tables
    assert not FLASHCARD_TABLES & tables

    await _alembic(url, "downgrade", "ai@base")
    assert (
        await _scalar(url, "SELECT count(*) FROM pg_namespace WHERE nspname = 'ai'")
        == 0
    )
