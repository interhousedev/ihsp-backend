"""admission_0042: the SAT Evidence-Based Reading and Writing catalog row."""

import asyncio

from tests.models.conftest import DatabaseFactory, run_alembic

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

SELECT_SAT_ERW = (
    "SELECT key, total_mode, (total->>'min')::float, (total->>'max')::float, "
    "(total->>'step')::float FROM admission.test_catalog WHERE key = 'sat_erw'"
)


async def test_sat_erw_catalog_row_is_seeded_and_removed(
    new_database: DatabaseFactory,
) -> None:
    """ADM-TESTS-SAT: sat_erw is seeded at 0042 (200-800, step 10, manual total)
    and removed again on downgrade."""
    url = await new_database()
    await asyncio.to_thread(run_alembic, url, "upgrade", "admission_0042_test_sat_erw")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            row = (await conn.execute(text(SELECT_SAT_ERW))).one()
        assert tuple(row) == ("sat_erw", "manual", 200.0, 800.0, 10.0)
        await asyncio.to_thread(
            run_alembic, url, "downgrade", "admission_0041_list_fee_status"
        )
        async with engine.connect() as conn:
            rows = (await conn.execute(text(SELECT_SAT_ERW))).all()
        assert rows == []
    finally:
        await engine.dispose()
