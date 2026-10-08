"""The ORM metadata holds exactly the 34 tables of README -> Models."""

from app.shared.db import models  # noqa: F401  (imports every module's ORM package)
from app.shared.db.base import Base

EXPECTED_TABLES = {
    # id (5)
    "id.users",
    "id.sessions",
    "id.telegram_links",
    "id.mcp_connectors",
    "id.audit_events",
    # academic (11)
    "academic.terms",
    "academic.groups",
    "academic.students",
    "academic.subjects",
    "academic.rooms",
    "academic.timetable_entries",
    "academic.lessons",
    "academic.homework_todos",
    "academic.marks",
    "academic.results",
    "academic.sync_runs",
    # files (1), links (1)
    "files.files",
    "links.links",
    # ai (5: chats and messages of module ai; sets, cards and the review log of
    # module flashcards)
    "ai.chats",
    "ai.chat_messages",
    "ai.flashcard_sets",
    "ai.flashcards",
    "ai.flashcard_reviews",
    # notify (1), admin (1), mail (1)
    "notify.notifications",
    "admin.broadcasts",
    "mail.mail_messages",
    # lms (8)
    "lms.courses",
    "lms.course_staff",
    "lms.course_steps",
    "lms.step_revisions",
    "lms.course_versions",
    "lms.enrollments",
    "lms.step_states",
    "lms.test_attempts",
}


def test_metadata_contains_every_table_of_the_models_readme() -> None:
    """README -> Models: 34 tables, each in the schema of its module."""
    actual = {table.fullname for table in Base.metadata.tables.values()}

    assert len(EXPECTED_TABLES) == 34
    assert actual == EXPECTED_TABLES


def test_every_table_has_a_primary_key_and_timestamps() -> None:
    """Every table has a primary key, created_at and updated_at."""
    for table in Base.metadata.tables.values():
        assert list(table.primary_key.columns), table.fullname
        assert "created_at" in table.c, table.fullname
        assert "updated_at" in table.c, table.fullname


def test_students_primary_key_is_user_id() -> None:
    """academic.students has no id column; user_id is the primary key."""
    table = Base.metadata.tables["academic.students"]

    assert [column.name for column in table.primary_key.columns] == ["user_id"]
    assert "id" not in table.c


def test_no_foreign_key_crosses_a_schema_except_inside_ai() -> None:
    """Foreign keys stay inside their schema (flashcards share schema ai)."""
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.schema == table.schema, foreign_key


def test_flashcards_branch_has_no_foreign_key_to_ai_tables() -> None:
    """The flashcards migration branch does not depend on the ai branch."""
    ai_tables = {"ai.chats", "ai.chat_messages"}
    for name in ("ai.flashcard_sets", "ai.flashcards", "ai.flashcard_reviews"):
        for foreign_key in Base.metadata.tables[name].foreign_keys:
            assert foreign_key.column.table.fullname not in ai_tables


def test_reserved_attribute_names_are_mapped_to_the_documented_columns() -> None:
    """The metadata columns are reached as ``meta`` in Python."""
    for name in ("id.audit_events", "files.files"):
        assert "metadata" in Base.metadata.tables[name].c
    assert "meta" in Base.metadata.tables["mail.mail_messages"].c
