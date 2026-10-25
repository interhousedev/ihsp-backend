"""notebooks_0005: library sources are accepted; existing sources stay valid."""

import asyncio

from tests.models.conftest import DatabaseFactory, run_alembic

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

NOTEBOOK_ID = "0198f000-0000-7000-8000-0000000000a1"
OLD_SOURCE_ID = "0198f000-0000-7000-8000-0000000000a2"
LIBRARY_SOURCE_ID = "0198f000-0000-7000-8000-0000000000a3"
INSERT_SOURCE = (
    "INSERT INTO notebooks.sources (id, notebook_id, owner_id, kind, title, position, "
    "status) VALUES (:id, :notebook, gen_random_uuid(), :kind, 'S', :position, 'ready')"
)


async def _alembic(url: str, *args: str) -> None:
    await asyncio.to_thread(run_alembic, url, *args)


async def _add_source(
    engine: AsyncEngine, source_id: str, kind: str, position: int
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(INSERT_SOURCE),
            {
                "id": source_id,
                "notebook": NOTEBOOK_ID,
                "kind": kind,
                "position": position,
            },
        )


async def _kinds(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT kind FROM notebooks.sources ORDER BY position")
        )
        return list(rows.scalars().all())


async def test_library_kinds_pass_the_upgrade_and_go_with_the_downgrade(
    new_database: DatabaseFactory,
) -> None:
    """LIB-10: 0005 extends the kind check; existing rows are valid before and after."""
    url = await new_database()
    await _alembic(url, "upgrade", "notebooks_0004")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO notebooks.notebooks (id, owner_id, title) "
                    "VALUES (:n, gen_random_uuid(), 'T')"
                ),
                {"n": NOTEBOOK_ID},
            )
        await _add_source(engine, OLD_SOURCE_ID, "lms_step", 1)
        with pytest.raises(DBAPIError):
            await _add_source(engine, LIBRARY_SOURCE_ID, "library_item", 2)

        await _alembic(url, "upgrade", "notebooks_0005")
        await _add_source(engine, LIBRARY_SOURCE_ID, "library_item", 2)
        await _add_source(
            engine, "0198f000-0000-7000-8000-0000000000a4", "library_notes", 3
        )
        assert await _kinds(engine) == ["lms_step", "library_item", "library_notes"]
        with pytest.raises(DBAPIError):
            await _add_source(
                engine, "0198f000-0000-7000-8000-0000000000a5", "bogus", 4
            )

        await _alembic(url, "downgrade", "notebooks_0004")
        assert await _kinds(engine) == ["lms_step"]
        with pytest.raises(DBAPIError):
            await _add_source(engine, LIBRARY_SOURCE_ID, "library_notes", 2)

        await _alembic(url, "upgrade", "notebooks_0005")
        assert await _kinds(engine) == ["lms_step"]
    finally:
        await engine.dispose()
