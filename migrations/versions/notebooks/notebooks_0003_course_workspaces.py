"""course workspaces

A notebook may belong to an LMS course instead of one student: the course staff
share it (`origin = 'course'`, `course_id`). One live workspace per course. The
auto notebook indexes now name the two auto origins instead of "not manual", so a
workspace is never treated as an auto notebook. Studio outputs get the two course
kinds (`course_plan`, `lesson_draft`) and `requested_by`, the staff member who asked
for an output in a workspace (budget, quota and the bell are theirs).

Revision ID: notebooks_0003
Revises: notebooks_0002
Create Date: 2026-10-08 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0003"
down_revision: str | Sequence[str] | None = "notebooks_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ORIGINS = ("manual", "subject_auto", "lesson_auto")
NEW_ORIGINS = (*OLD_ORIGINS, "course")
OLD_KINDS = (
    "report",
    "mind_map",
    "flashcards",
    "quiz",
    "data_table",
    "slides",
    "infographic",
    "audio_overview",
)
NEW_KINDS = (*OLD_KINDS, "course_plan", "lesson_draft")

OLD_AUTO_TARGET = (
    "(origin = 'manual' AND subject_id IS NULL AND lesson_id IS NULL "
    "AND auto_settings IS NULL) "
    "OR (origin = 'subject_auto' AND subject_id IS NOT NULL "
    "AND lesson_id IS NULL AND auto_settings IS NOT NULL) "
    "OR (origin = 'lesson_auto' AND lesson_id IS NOT NULL "
    "AND subject_id IS NOT NULL AND auto_settings IS NOT NULL)"
)
NEW_AUTO_TARGET = (
    "(origin = 'manual' AND subject_id IS NULL AND lesson_id IS NULL "
    "AND auto_settings IS NULL AND course_id IS NULL) "
    "OR (origin = 'subject_auto' AND subject_id IS NOT NULL "
    "AND lesson_id IS NULL AND auto_settings IS NOT NULL "
    "AND course_id IS NULL) "
    "OR (origin = 'lesson_auto' AND lesson_id IS NOT NULL "
    "AND subject_id IS NOT NULL AND auto_settings IS NOT NULL "
    "AND course_id IS NULL) "
    "OR (origin = 'course' AND course_id IS NOT NULL AND subject_id IS NULL "
    "AND lesson_id IS NULL AND auto_settings IS NULL)"
)
OLD_AUTO = "origin <> 'manual' AND deleted_at IS NULL"
NEW_AUTO = "origin IN ('subject_auto', 'lesson_auto') AND deleted_at IS NULL"
AUTO_INDEXES = (
    ("ix_notebooks_subject_id_auto", "subject_id"),
    ("ix_notebooks_auto_synced_at", "auto_synced_at"),
)
WORKSPACE = "origin = 'course' AND deleted_at IS NULL"


def _in_list(column: str, values: Sequence[str]) -> str:
    """The CHECK text of a VARCHAR enumeration (as `sa.Enum` writes it)."""
    listed = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({listed})"


def _replace_check(table: str, name: str, condition: str) -> None:
    """Drop a CHECK constraint and create it again with a new condition."""
    op.drop_constraint(op.f(name), table, schema="notebooks", type_="check")
    op.create_check_constraint(op.f(name), table, condition, schema="notebooks")


def _replace_auto_indexes(old: str, new: str) -> None:
    """Recreate the two partial indexes of auto notebooks with a new predicate."""
    for name, column in AUTO_INDEXES:
        op.drop_index(
            name,
            table_name="notebooks",
            schema="notebooks",
            postgresql_where=sa.text(old),
        )
        op.create_index(
            name,
            "notebooks",
            [column],
            unique=False,
            schema="notebooks",
            postgresql_where=sa.text(new),
        )


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "notebooks",
        sa.Column("course_id", sa.Uuid(), nullable=True),
        schema="notebooks",
    )
    _replace_check("notebooks", "ck_notebooks_origin", _in_list("origin", NEW_ORIGINS))
    _replace_check("notebooks", "ck_notebooks_auto_target", NEW_AUTO_TARGET)
    _replace_auto_indexes(OLD_AUTO, NEW_AUTO)
    op.create_index(
        "ix_notebooks_course_id_workspace",
        "notebooks",
        ["course_id"],
        unique=True,
        schema="notebooks",
        postgresql_where=sa.text(WORKSPACE),
    )
    _replace_check("artifacts", "ck_artifacts_kind", _in_list("kind", NEW_KINDS))
    op.add_column(
        "artifacts",
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        schema="notebooks",
    )


def downgrade() -> None:
    """Downgrade schema (course workspaces and course outputs are deleted)."""
    # Sources, passages links, messages and outputs of a workspace cascade.
    op.execute("DELETE FROM notebooks.notebooks WHERE origin = 'course'")
    op.execute(
        "DELETE FROM notebooks.artifacts "
        "WHERE kind IN ('course_plan', 'lesson_draft')"
    )
    op.drop_column("artifacts", "requested_by", schema="notebooks")
    _replace_check("artifacts", "ck_artifacts_kind", _in_list("kind", OLD_KINDS))
    op.drop_index(
        "ix_notebooks_course_id_workspace",
        table_name="notebooks",
        schema="notebooks",
        postgresql_where=sa.text(WORKSPACE),
    )
    _replace_auto_indexes(NEW_AUTO, OLD_AUTO)
    _replace_check("notebooks", "ck_notebooks_auto_target", OLD_AUTO_TARGET)
    _replace_check("notebooks", "ck_notebooks_origin", _in_list("origin", OLD_ORIGINS))
    op.drop_column("notebooks", "course_id", schema="notebooks")
