"""Migrations: upgrade, downgrade, upgrade again, and agreement with the models.

Each ``alembic`` run is a subprocess (about as slow as a real deployment step), so
the tests are few and each walks through a whole scenario.
"""

import asyncio

from app.shared.db import models  # noqa: F401  (imports every module's ORM package)
from app.shared.db.base import Base
from tests.models.conftest import DatabaseFactory, run_alembic

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

SCHEMAS = {
    "id",
    "academic",
    "files",
    "links",
    "ai",
    "notify",
    "admin",
    "mail",
    "lms",
    "notebooks",
    "library",
    "vectors",
    "dashboard",
}
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
    """On an empty database one ``upgrade heads`` creates the 41 tables of the
    models, with no difference left for autogenerate, and btree_gist and pg_trgm."""
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
    assert (
        await _scalar(
            url, "SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'"
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


async def test_notebooks_branch_stands_alone_and_keeps_the_extension(
    new_database: DatabaseFactory,
) -> None:
    """notebooks@head needs no other branch; removing it leaves pg_trgm in place."""
    url = await new_database()

    await _alembic(url, "upgrade", "notebooks@head")
    assert await _tables(url) == {
        table for table in _model_tables() if table.startswith("notebooks.")
    }
    assert (
        await _scalar(
            url,
            "SELECT is_generated FROM information_schema.columns WHERE "
            "table_schema = 'notebooks' AND table_name = 'passages' "
            "AND column_name = 'search_vector'",
        )
        == "ALWAYS"
    )

    await _alembic(url, "downgrade", "notebooks@base")
    assert await _tables(url) == set()
    assert (
        await _scalar(
            url, "SELECT count(*) FROM pg_namespace WHERE nspname = 'notebooks'"
        )
        == 0
    )
    assert (
        await _scalar(
            url, "SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'"
        )
        == 1
    )


async def _insert_notification(url: str, notification_type: str) -> None:
    """Insert one notification row of the given type (committed)."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO notify.notifications (id, user_id, type, dedupe_key) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), :type, :key)"
                ),
                {"type": notification_type, "key": f"{notification_type}:k"},
            )
    finally:
        await engine.dispose()


async def test_notify_0002_allows_the_notebook_notification_type_and_reverts(
    new_database: DatabaseFactory,
) -> None:
    """NB-21: the type column widens for ``notebook_artifact_ready``; going back
    deletes those rows and forbids the value again."""
    url = await new_database()
    width = (
        "SELECT character_maximum_length FROM information_schema.columns WHERE "
        "table_schema = 'notify' AND table_name = 'notifications' "
        "AND column_name = 'type'"
    )

    await _alembic(url, "upgrade", "notify_0001")
    assert await _scalar(url, width) == len("otp_reset_requested")
    with pytest.raises(DBAPIError):
        await _insert_notification(url, "notebook_artifact_ready")

    await _alembic(url, "upgrade", "notify@head")
    await _insert_notification(url, "notebook_artifact_ready")
    await _insert_notification(url, "marks")
    assert await _scalar(url, width) == len("library_item_changes_requested")
    with pytest.raises(DBAPIError):
        await _insert_notification(url, "no_such_type")

    await _alembic(url, "downgrade", "notify_0001")
    assert await _scalar(url, "SELECT count(*) FROM notify.notifications") == 1
    assert await _scalar(url, width) == len("otp_reset_requested")
    with pytest.raises(DBAPIError):
        await _insert_notification(url, "notebook_artifact_ready")


async def test_notify_0003_adds_push_subscriptions_with_a_unique_endpoint(
    new_database: DatabaseFactory,
) -> None:
    """Web Push: one row per browser endpoint; downgrading drops only that table."""
    url = await new_database()

    await _alembic(url, "upgrade", "notify@head")
    assert "notify.push_subscriptions" in await _tables(url)
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            insert = text(
                "INSERT INTO notify.push_subscriptions "
                "(id, user_id, endpoint, p256dh, auth) "
                "VALUES (gen_random_uuid(), gen_random_uuid(), :endpoint, 'k', 'a')"
            )
            await conn.execute(insert, {"endpoint": "https://fcm.googleapis.com/x"})
        with pytest.raises(DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(insert, {"endpoint": "https://fcm.googleapis.com/x"})
    finally:
        await engine.dispose()

    await _alembic(url, "downgrade", "notify_0002")
    tables = await _tables(url)
    assert "notify.push_subscriptions" not in tables
    assert "notify.notifications" in tables


def _compare_schemas(connection: Connection, schemas: set[str]) -> list[object]:
    """Autogenerate differences restricted to some schemas (others may be in flux)."""

    def include_object(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = obj if type_ == "table" else getattr(obj, "table", None)
        return table is None or getattr(table, "schema", None) in schemas

    context = MigrationContext.configure(
        connection,
        opts={
            "include_schemas": True,
            "include_name": lambda name, type_, parents: (
                name in schemas if type_ == "schema" else True
            ),
            "include_object": include_object,
            "compare_type": True,
            "version_table_schema": "public",
        },
    )
    return list(compare_metadata(context, Base.metadata))


async def test_academic_0003_assessments_match_the_models_and_revert(
    new_database: DatabaseFactory,
) -> None:
    """Exams: assessments and terms.control_periods match the ORM and revert."""
    url = await new_database()

    await _alembic(url, "upgrade", "academic@head")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            assert await conn.run_sync(_compare_schemas, {"academic"}) == []
    finally:
        await engine.dispose()
    assert "academic.assessments" in await _tables(url)
    assert (
        await _scalar(
            url,
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = "
            "'academic' AND table_name = 'terms' AND column_name = 'control_periods'",
        )
        == 1
    )

    await _alembic(url, "downgrade", "academic_0002")

    assert "academic.assessments" not in await _tables(url)
    assert (
        await _scalar(
            url,
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = "
            "'academic' AND table_name = 'terms' AND column_name = 'control_periods'",
        )
        == 0
    )


async def test_notify_0004_allows_the_assessment_reminder_type_and_reverts(
    new_database: DatabaseFactory,
) -> None:
    """The reminder type is allowed after 0004; going back deletes its rows."""
    url = await new_database()

    await _alembic(url, "upgrade", "notify_0003")
    with pytest.raises(DBAPIError):
        await _insert_notification(url, "assessment_reminder")

    await _alembic(url, "upgrade", "notify@head")
    await _insert_notification(url, "assessment_reminder")
    await _insert_notification(url, "notebook_artifact_ready")
    with pytest.raises(DBAPIError):
        await _insert_notification(url, "no_such_type")

    await _alembic(url, "downgrade", "notify_0003")
    assert await _scalar(url, "SELECT count(*) FROM notify.notifications") == 1
    with pytest.raises(DBAPIError):
        await _insert_notification(url, "assessment_reminder")


async def test_notify_0005_allows_the_library_types_and_reverts(
    new_database: DatabaseFactory,
) -> None:
    """LIB-5: the seven library types are allowed after 0005; going back drops them."""
    url = await new_database()
    library_types = [
        "library_item_approved",
        "library_item_changes_requested",
        "library_item_rejected",
        "library_item_unpublished",
        "library_queue_waiting",
        "library_report_filed",
        "library_reading_list_new",
    ]

    await _alembic(url, "upgrade", "notify_0004")
    for notification_type in library_types:
        with pytest.raises(DBAPIError):
            await _insert_notification(url, notification_type)

    await _alembic(url, "upgrade", "notify@head")
    for notification_type in library_types:
        await _insert_notification(url, notification_type)
    await _insert_notification(url, "assessment_reminder")
    with pytest.raises(DBAPIError):
        await _insert_notification(url, "no_such_type")

    await _alembic(url, "downgrade", "notify_0004")
    assert await _scalar(url, "SELECT count(*) FROM notify.notifications") == 1
    await _insert_notification(url, "notebook_artifact_ready")
    for notification_type in library_types:
        with pytest.raises(DBAPIError):
            await _insert_notification(url, notification_type)


async def test_academic_0003_recomputes_semester_marks_by_the_new_aca_15(
    new_database: DatabaseFactory,
) -> None:
    """Lesson 4.00 and midterm 5.00 without a final were 4.00; now they are 4.50."""
    url = await new_database()
    await _alembic(url, "upgrade", "academic_0002")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for statement in (
                "INSERT INTO academic.groups (id, name, slug, status) VALUES "
                "('00000000-0000-4000-8000-000000000001', '2TN2', '2tn2', 'active')",
                "INSERT INTO academic.subjects (id, name) VALUES "
                "('00000000-0000-4000-8000-000000000002', '{}'::jsonb), "
                "('00000000-0000-4000-8000-000000000003', '{}'::jsonb)",
                "INSERT INTO academic.students (user_id, group_id, status) VALUES "
                "('00000000-0000-4000-8000-000000000004', "
                "'00000000-0000-4000-8000-000000000001', 'active')",
            ):
                await conn.execute(text(statement))
            marks = [
                ("2", "lesson", 5, "2026-10-01"),
                ("2", "lesson", 3, "2026-10-02"),
                ("2", "midterm", 5, "2026-10-03"),
                ("3", "lesson", 4, "2026-10-01"),
            ]
            for subject, kind, value, day in marks:
                await conn.execute(
                    text(
                        "INSERT INTO academic.marks (id, student_id, subject_id, "
                        "semester, type, value, date) VALUES (gen_random_uuid(), "
                        "'00000000-0000-4000-8000-000000000004', "
                        f"'00000000-0000-4000-8000-00000000000{subject}', 3, "
                        f"'{kind}', {value}, '{day}')"
                    )
                )
            await conn.execute(
                text(
                    "INSERT INTO academic.results (id, student_id, semester, "
                    "subject_id, value) VALUES "
                    "(gen_random_uuid(), '00000000-0000-4000-8000-000000000004', 3, "
                    "'00000000-0000-4000-8000-000000000002', 4.00), "
                    "(gen_random_uuid(), '00000000-0000-4000-8000-000000000004', 3, "
                    "'00000000-0000-4000-8000-000000000003', 4.00), "
                    "(gen_random_uuid(), '00000000-0000-4000-8000-000000000004', 3, "
                    "NULL, 4.25)"
                )
            )
    finally:
        await engine.dispose()

    await _alembic(url, "upgrade", "academic@head")

    values = await _scalar(
        url,
        "SELECT string_agg(coalesce(value::text, 'null'), ',' ORDER BY subject_id "
        "NULLS LAST) FROM academic.results",
    )
    assert values == "4.50,4.00,4.25"  # (4.00 + 5.00) / 2; lesson only; GPA row kept


async def _insert_step(url: str, course_id: str, via: str) -> None:
    """Insert one lms step whose two ``via`` columns hold the value (committed)."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO lms.course_steps (id, course_id, draft, draft_hash, "
                    "draft_updated_via, created_via) VALUES (gen_random_uuid(), "
                    ":course, '{}'::jsonb, 'h', :via, :via)"
                ),
                {"course": course_id, "via": via},
            )
    finally:
        await engine.dispose()


async def test_lms_0002_allows_ai_as_the_origin_of_a_step_and_reverts(
    new_database: DatabaseFactory,
) -> None:
    """LMS-AI: ``ai`` is allowed after 0002 in both columns; going back turns the
    AI steps into MCP steps (also machine-made) and forbids the value again."""
    url = await new_database()
    course = "00000000-0000-4000-8000-0000000000c1"
    await _alembic(url, "upgrade", "lms_0001")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO lms.courses (id, slug, title, visibility, created_by, "
                    "draft_meta, outline_hash) VALUES (:id, 'c-1', 'C', 'public', "
                    "gen_random_uuid(), '{}'::jsonb, 'h')"
                ),
                {"id": course},
            )
    finally:
        await engine.dispose()
    with pytest.raises(DBAPIError):
        await _insert_step(url, course, "ai")

    await _alembic(url, "upgrade", "lms@head")
    await _insert_step(url, course, "ai")
    await _insert_step(url, course, "mcp")
    await _insert_step(url, course, "ui")
    with pytest.raises(DBAPIError):
        await _insert_step(url, course, "robot")

    await _alembic(url, "downgrade", "lms_0001")
    via = await _scalar(
        url,
        "SELECT string_agg(created_via || '/' || draft_updated_via, ',' "
        "ORDER BY created_via) FROM lms.course_steps",
    )
    assert via == "mcp/mcp,mcp/mcp,ui/ui"
    with pytest.raises(DBAPIError):
        await _insert_step(url, course, "ai")
