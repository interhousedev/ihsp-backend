"""Hidden flash card notebooks.

A student's one hidden notebook (`origin = 'flashcards'`) holds the sources chosen for
"Add new questions with AI" of a flash card set, so Studio can generate from them.

Revision ID: notebooks_0013
Revises: notebooks_0012
Create Date: 2026-11-04 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0013"
down_revision: str | Sequence[str] | None = "notebooks_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ORIGINS = ("manual", "subject_auto", "lesson_auto", "course", "course_student")
NEW_ORIGINS = (*OLD_ORIGINS, "flashcards")

OLD_TARGET = (
    "(origin = 'manual' AND subject_id IS NULL AND lesson_id IS NULL "
    "AND auto_settings IS NULL AND course_id IS NULL) "
    "OR (origin = 'subject_auto' AND subject_id IS NOT NULL "
    "AND lesson_id IS NULL AND auto_settings IS NOT NULL "
    "AND course_id IS NULL) "
    "OR (origin = 'lesson_auto' AND lesson_id IS NOT NULL "
    "AND subject_id IS NOT NULL AND auto_settings IS NOT NULL "
    "AND course_id IS NULL) "
    "OR (origin IN ('course', 'course_student') AND course_id IS NOT NULL "
    "AND subject_id IS NULL AND lesson_id IS NULL AND auto_settings IS NULL)"
)
NEW_TARGET = (
    OLD_TARGET + " OR (origin = 'flashcards' AND course_id IS NULL "
    "AND subject_id IS NULL AND lesson_id IS NULL AND auto_settings IS NULL)"
)
HIDDEN = "origin = 'flashcards' AND deleted_at IS NULL"


def _in_list(column: str, values: Sequence[str]) -> str:
    """The CHECK text of a VARCHAR enumeration (as `sa.Enum` writes it)."""
    listed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({listed})"


def _replace_check(name: str, condition: str) -> None:
    """Drop a CHECK constraint of notebooks and create it again."""
    op.drop_constraint(op.f(name), "notebooks", schema="notebooks", type_="check")
    op.create_check_constraint(op.f(name), "notebooks", condition, schema="notebooks")


def upgrade() -> None:
    """Upgrade schema."""
    _replace_check("ck_notebooks_origin", _in_list("origin", NEW_ORIGINS))
    _replace_check("ck_notebooks_auto_target", NEW_TARGET)
    op.create_index(
        "ix_notebooks_owner_id_flashcards",
        "notebooks",
        ["owner_id"],
        unique=True,
        schema="notebooks",
        postgresql_where=sa.text(HIDDEN),
    )


def downgrade() -> None:
    """Downgrade schema (the hidden notebooks are deleted)."""
    op.execute("DELETE FROM notebooks.notebooks WHERE origin = 'flashcards'")
    op.drop_index(
        "ix_notebooks_owner_id_flashcards",
        table_name="notebooks",
        schema="notebooks",
        postgresql_where=sa.text(HIDDEN),
    )
    _replace_check("ck_notebooks_auto_target", OLD_TARGET)
    _replace_check("ck_notebooks_origin", _in_list("origin", OLD_ORIGINS))
