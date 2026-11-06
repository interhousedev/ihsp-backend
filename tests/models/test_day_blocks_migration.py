"""academic_0011: per-day blocks keep current lessons and retire old Saturday rows."""

import asyncio
import json
import uuid

from tests.models.conftest import DatabaseFactory, run_alembic

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def test_the_migration_keeps_blocks_and_retires_old_saturdays(
    new_database: DatabaseFactory,
) -> None:
    """Weekday blocks stay, Saturday ones go; an old Saturday entry gets weekday 0."""
    url = await new_database()
    await asyncio.to_thread(run_alembic, url, "upgrade", "heads")
    await asyncio.to_thread(run_alembic, url, "downgrade", "academic_0010")
    term_id, subject_id = uuid.uuid4(), uuid.uuid4()
    monday, saturday = uuid.uuid4(), uuid.uuid4()
    bells = [
        {"period": 1, "start": "08:30", "end": "09:50", "weekdays": [1, 2, 3, 4, 5, 6]},
        {"period": 7, "start": "09:00", "end": "09:40", "weekdays": [6]},
    ]
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO academic.terms "
                    "(id, academic_year, half, starts_on, ends_on, bells) VALUES "
                    "(:id, '2026-2027', 1, '2026-09-01', '2026-12-25', "
                    "CAST(:bells AS jsonb))"
                ),
                {"id": term_id, "bells": json.dumps(bells)},
            )
            await conn.execute(
                text(
                    "INSERT INTO academic.subjects (id, name) "
                    "VALUES (:id, '{}'::jsonb)"
                ),
                {"id": subject_id},
            )
            for entry_id, weekday in ((monday, 1), (saturday, 6)):
                await conn.execute(
                    text(
                        "INSERT INTO academic.timetable_entries "
                        "(id, term_id, weekday, period, week_parity, subject_id, "
                        "audience, valid_from) VALUES (:id, :term, :day, 1, 'every', "
                        ":subject, ARRAY['g'], '2026-09-01')"
                    ),
                    {
                        "id": entry_id,
                        "term": term_id,
                        "day": weekday,
                        "subject": subject_id,
                    },
                )

        await asyncio.to_thread(run_alembic, url, "upgrade", "heads")

        async with engine.connect() as conn:
            stored = await conn.scalar(
                text("SELECT bells FROM academic.terms WHERE id = :id"),
                {"id": term_id},
            )
            days = dict(
                (
                    await conn.execute(
                        text("SELECT id, weekday FROM academic.timetable_entries")
                    )
                ).all()
            )
        assert [(b["period"], b["weekdays"]) for b in stored] == [(1, [1, 2, 3, 4, 5])]
        assert stored[0]["start"] == "08:30"
        assert days == {monday: 1, saturday: 0}
    finally:
        await engine.dispose()
