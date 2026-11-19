"""admission_0040: opportunity kind `research` and the seeded catalog entries."""

import asyncio
import uuid

from tests.models.conftest import DatabaseFactory, run_alembic

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

COUNT_SEEDS = (
    "SELECT count(*) FROM admission.opportunities "
    "WHERE title IN ('Beamline for Schools', 'Technovation Girls')"
)
INSERT = (
    "INSERT INTO admission.opportunities (id, kind, title, payload, created_by) "
    "VALUES (:id, :kind, 'X', '{}'::jsonb, :sys)"
)
SYSTEM = uuid.UUID(int=0)


async def test_opp_research_migration_seeds_and_downgrade_removes(
    new_database: DatabaseFactory,
) -> None:
    """ADM-MIG-RESEARCH: seeds and `research` exist at 0040, vanish on downgrade."""
    url = await new_database()
    await asyncio.to_thread(run_alembic, url, "upgrade", "admission_0040_opp_research")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            assert await conn.scalar(text(COUNT_SEEDS)) == 2
            kinds = set(
                (
                    await conn.execute(
                        text("SELECT DISTINCT kind FROM admission.opportunities")
                    )
                ).scalars()
            )
            assert "research" in kinds
        async with engine.begin() as conn:
            await conn.execute(
                text(INSERT),
                {"id": uuid.uuid4(), "kind": "research", "sys": SYSTEM},
            )
        await asyncio.to_thread(
            run_alembic, url, "downgrade", "admission_0039_round_scea"
        )
        async with engine.connect() as conn:
            assert await conn.scalar(text(COUNT_SEEDS)) == 0
            assert not await conn.scalar(
                text(
                    "SELECT count(*) FROM admission.opportunities "
                    "WHERE kind = 'research'"
                )
            )
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(INSERT),
                    {"id": uuid.uuid4(), "kind": "research", "sys": SYSTEM},
                )
        await asyncio.to_thread(run_alembic, url, "upgrade", "heads")
        async with engine.connect() as conn:
            assert await conn.scalar(text(COUNT_SEEDS)) == 2
    finally:
        await engine.dispose()
