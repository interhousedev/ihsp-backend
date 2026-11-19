"""admission_0039: round SCEA is allowed; the downgrade maps it to REA."""

import asyncio
import uuid

from tests.models.conftest import DatabaseFactory, run_alembic

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

INSERT_ENTRY = (
    "INSERT INTO admission.list_entries (id, student_id, institution_id, round) "
    "VALUES (:id, :student, :inst, :round)"
)


async def _entry(conn: AsyncConnection, inst: uuid.UUID, round_: str) -> uuid.UUID:
    entry = uuid.uuid4()
    await conn.execute(
        text(INSERT_ENTRY),
        {"id": entry, "student": uuid.uuid4(), "inst": inst, "round": round_},
    )
    return entry


async def test_round_scea_migration_maps_to_rea_on_downgrade(
    new_database: DatabaseFactory,
) -> None:
    """ADM-MIG-SCEA: SCEA is allowed at 0039 and becomes REA on downgrade."""
    url = await new_database()
    await asyncio.to_thread(run_alembic, url, "upgrade", "admission_0039_round_scea")
    engine = create_async_engine(url)
    try:
        inst = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO admission.institutions (id, name, country) "
                    "VALUES (:id, 'Test U', 'US')"
                ),
                {"id": inst},
            )
            scea = await _entry(conn, inst, "SCEA")
            rd = await _entry(conn, inst, "RD")
        await asyncio.to_thread(
            run_alembic, url, "downgrade", "admission_0038_essay_invites"
        )
        async with engine.connect() as conn:
            rows = dict(
                (
                    await conn.execute(
                        text("SELECT id, round FROM admission.list_entries")
                    )
                )
                .tuples()
                .all()
            )
            assert rows[scea] == "REA"
            assert rows[rd] == "RD"
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await _entry(conn, inst, "SCEA")
        await asyncio.to_thread(run_alembic, url, "upgrade", "heads")
        async with engine.begin() as conn:
            await _entry(conn, inst, "SCEA")
    finally:
        await engine.dispose()
