"""certificates_0003: level, score, percent, subject, year and serial as custom fields.

Up from the seeded types (cefr, sat, national) and an entry with column values, then
down again: the columns, the flags and the values come back.
"""

import asyncio

from tests.models.conftest import DatabaseFactory, run_alembic

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

STUDENT = "22222222-2222-2222-2222-222222222222"


async def _alembic(url: str, *args: str) -> None:
    """Run alembic without blocking the event loop."""
    await asyncio.to_thread(run_alembic, url, *args)


async def _run(url: str, sql: str) -> object:
    """Run one statement in its own transaction; return the first value, if any."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql))
            return result.scalar() if result.returns_rows else None
    finally:
        await engine.dispose()


def _cefr_entry(serial: str) -> str:
    """INSERT of a CEFR entry with column values (the 0002 shape)."""
    return (
        "INSERT INTO certificates.entries (id, student_id, type_id, level, score, "
        "subject, year, serial, source, issued_at) SELECT gen_random_uuid(), "
        f"'{STUDENT}', id, 'B2', 72, 'English', 2025, '{serial}', 'emis', "
        "DATE '2025-03-15' FROM certificates.types WHERE code = 'cefr' RETURNING id"
    )


FIELDS = (
    "SELECT string_agg(f->>'key', ',' ORDER BY ord) FROM certificates.types t, "
    "jsonb_array_elements(t.custom_fields) WITH ORDINALITY AS a(f, ord) "
    "WHERE t.code = '{code}'"
)


async def test_0003_turns_the_flags_into_custom_fields_and_takes_them_back(
    new_database: DatabaseFactory,
) -> None:
    """Seeded types get their fields, the entry keeps its values, and the downgrade
    restores the columns, the flags and the values."""
    url = await new_database()
    await _alembic(url, "upgrade", "certificates_0002")
    await _run(url, _cefr_entry("C-1"))

    await _alembic(url, "upgrade", "certificates_0003")

    assert await _run(url, FIELDS.format(code="cefr")) == (
        "level,score,year,subject,serial"
    )
    assert await _run(url, FIELDS.format(code="national")) == (
        "level,score,percent,year,subject,serial"
    )
    assert await _run(url, FIELDS.format(code="volunteering")) == ("year,serial")
    levels = await _run(
        url,
        "SELECT f->'options' FROM certificates.types t, jsonb_array_elements("
        "t.custom_fields) AS a(f) WHERE t.code = 'cefr' AND f->>'key' = 'level'",
    )
    assert levels == ["A1", "A2", "B1", "B2", "C1", "C2"]
    bounds = await _run(
        url,
        "SELECT (f->>'min')::float * 10000 + (f->>'max')::float FROM "
        "certificates.types t, jsonb_array_elements(t.custom_fields) AS a(f) "
        "WHERE t.code = 'sat' AND f->>'key' = 'score'",
    )
    assert bounds == 400 * 10000 + 1600
    percent = await _run(
        url,
        "SELECT (f->>'max')::float FROM certificates.types t, "
        "jsonb_array_elements(t.custom_fields) AS a(f) "
        "WHERE t.code = 'national' AND f->>'key' = 'percent'",
    )
    assert percent == 100.0
    assert await _run(
        url,
        'SELECT custom_values = CAST(\'{"level": "B2", "score": 72, '
        '"subject": "English", "year": 2025, "serial": "C-1"}\' AS jsonb) '
        "FROM certificates.entries",
    )
    with pytest.raises(DBAPIError):
        await _run(url, _cefr_entry("C-1"))  # the serial is still unique per type

    await _alembic(url, "downgrade", "certificates_0002")

    assert (
        await _run(
            url,
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = "
            "'certificates' AND table_name = 'entries' AND column_name = 'level'",
        )
        == 1
    )
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT level, score, subject, year, serial "
                        "FROM certificates.entries"
                    )
                )
            ).one()
    finally:
        await engine.dispose()
    assert tuple(row) == ("B2", 72.0, "English", 2025, "C-1")
    assert await _run(
        url,
        "SELECT asks_level AND asks_score AND asks_subject AND NOT asks_percent "
        "FROM certificates.types WHERE code = 'cefr'",
    )
    assert await _run(
        url,
        "SELECT levels FROM certificates.types WHERE code = 'cefr'",
    ) == ["A1", "A2", "B1", "B2", "C1", "C2"]
    assert (
        await _run(
            url,
            "SELECT custom_fields FROM certificates.types WHERE code = 'cefr'",
        )
        == []
    )
