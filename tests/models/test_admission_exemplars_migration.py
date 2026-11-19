"""admission_0037: the exemplar library table and the curator permission."""

import asyncio

from tests.models.conftest import DatabaseFactory, run_alembic

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def test_exemplars_migration_runs_up_down_up(
    new_database: DatabaseFactory,
) -> None:
    """ADM-EXM-10: the table exists after upgrade, goes on downgrade, returns."""
    url = await new_database()
    await asyncio.to_thread(run_alembic, url, "upgrade", "heads")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            perms = await conn.scalar(
                text(
                    "SELECT permissions FROM admission.staff_roles "
                    "WHERE key = 'counselor_full'"
                )
            )
            assert perms is None or "exemplars:curate" in perms
            assert await conn.scalar(
                text("SELECT to_regclass('admission.exemplar_essays') IS NOT NULL")
            )
        await asyncio.to_thread(
            run_alembic, url, "downgrade", "admission_0036_essay_reviews"
        )
        async with engine.connect() as conn:
            assert not await conn.scalar(
                text("SELECT to_regclass('admission.exemplar_essays') IS NOT NULL")
            )
        await asyncio.to_thread(run_alembic, url, "upgrade", "heads")
        async with engine.connect() as conn:
            assert await conn.scalar(
                text("SELECT to_regclass('admission.exemplar_essays') IS NOT NULL")
            )
    finally:
        await engine.dispose()
