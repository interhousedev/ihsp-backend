"""admission_0043: supplement prompt limit unit, minimum and choice group columns."""

import asyncio

from tests.models.conftest import DatabaseFactory, run_alembic

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

SELECT_COLUMNS = (
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_schema = 'admission' AND table_name = 'supp_prompts' "
    "AND column_name IN ('limit_unit', 'limit_min', 'choice_group')"
)


async def test_supp_prompt_limit_columns_are_added_and_removed(
    new_database: DatabaseFactory,
) -> None:
    """ADM-CAT-API-LIMITS: 0043 adds limit_unit, limit_min and choice_group,
    and downgrade removes them again."""
    url = await new_database()
    await asyncio.to_thread(run_alembic, url, "upgrade", "admission_0043_supp_limits")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            cols = {r[0] for r in (await conn.execute(text(SELECT_COLUMNS))).all()}
        assert cols == {"limit_unit", "limit_min", "choice_group"}
        await asyncio.to_thread(
            run_alembic, url, "downgrade", "admission_0042_test_sat_erw"
        )
        async with engine.connect() as conn:
            rows = (await conn.execute(text(SELECT_COLUMNS))).all()
        assert rows == []
    finally:
        await engine.dispose()
