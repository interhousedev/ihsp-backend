"""admission_0035: essay text columns become bytea and come back on downgrade."""

import asyncio

from tests.models.conftest import DatabaseFactory, run_alembic

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TYPE_SQL = (
    "SELECT data_type FROM information_schema.columns "
    "WHERE table_schema = 'admission' AND table_name = 'essays' "
    "AND column_name = 'body'"
)


async def test_essay_sealed_migration_runs_up_down_up(
    new_database: DatabaseFactory,
) -> None:
    """ADM-CRYPT-16: body is bytea after upgrade, text after downgrade, then bytea."""
    url = await new_database()
    await asyncio.to_thread(run_alembic, url, "upgrade", "admission_0035_essay_sealed")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            assert await conn.scalar(text(TYPE_SQL)) == "bytea"
        await asyncio.to_thread(
            run_alembic, url, "downgrade", "admission_0034_opp_author_null"
        )
        async with engine.connect() as conn:
            assert await conn.scalar(text(TYPE_SQL)) == "text"
        await asyncio.to_thread(run_alembic, url, "upgrade", "heads")
        async with engine.connect() as conn:
            assert await conn.scalar(text(TYPE_SQL)) == "bytea"
    finally:
        await engine.dispose()


async def test_essay_sealed_migration_deletes_plaintext_essays(
    new_database: DatabaseFactory,
) -> None:
    """ADM-CRYPT-17: upgrade deletes existing plaintext essays; downgrade works."""
    url = await new_database()
    await asyncio.to_thread(
        run_alembic, url, "upgrade", "admission_0034_opp_author_null"
    )
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO admission.essays (id, student_id, body) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), 'plain text')"
                )
            )
        await asyncio.to_thread(
            run_alembic, url, "upgrade", "admission_0035_essay_sealed"
        )
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM admission.essays")) == 0
        await asyncio.to_thread(
            run_alembic, url, "downgrade", "admission_0034_opp_author_null"
        )
        async with engine.connect() as conn:
            assert await conn.scalar(text(TYPE_SQL)) == "text"
    finally:
        await engine.dispose()
