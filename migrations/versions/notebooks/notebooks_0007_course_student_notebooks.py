"""Course student notebooks.

An enrolled student gets a notebook of the LMS course (`origin = 'course_student'`,
`course_id`): the course materials are its sources, kept by the system. One live
notebook per student and course; the course workspace of the staff (`course`) is
unaffected.

Revision ID: notebooks_0007
Revises: notebooks_0006
Create Date: 2026-10-10 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0007"
down_revision: str | Sequence[str] | None = "notebooks_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ORIGINS = ("manual", "subject_auto", "lesson_auto", "course")
NEW_ORIGINS = (*OLD_ORIGINS, "course_student")

OLD_TARGET_TAIL = (
    "OR (origin = 'course' AND course_id IS NOT NULL AND subject_id IS NULL "
    "AND lesson_id IS NULL AND auto_settings IS NULL)"
)
NEW_TARGET_TAIL = (
    "OR (origin IN ('course', 'course_student') AND course_id IS NOT NULL "
    "AND subject_id IS NULL AND lesson_id IS NULL AND auto_settings IS NULL)"
)
TARGET_HEAD = (
    "(origin = 'manual' AND subject_id IS NULL AND lesson_id IS NULL "
    "AND auto_settings IS NULL AND course_id IS NULL) "
    "OR (origin = 'subject_auto' AND subject_id IS NOT NULL "
    "AND lesson_id IS NULL AND auto_settings IS NOT NULL "
    "AND course_id IS NULL) "
    "OR (origin = 'lesson_auto' AND lesson_id IS NOT NULL "
    "AND subject_id IS NOT NULL AND auto_settings IS NOT NULL "
    "AND course_id IS NULL) "
)
STUDENT = "origin = 'course_student' AND deleted_at IS NULL"


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
    op.alter_column(
        "notebooks",
        "origin",
        schema="notebooks",
        existing_type=sa.String(length=12),
        type_=sa.String(length=14),
        existing_nullable=False,
        existing_server_default=sa.text("'manual'"),
    )
    _replace_check("ck_notebooks_origin", _in_list("origin", NEW_ORIGINS))
    _replace_check("ck_notebooks_auto_target", TARGET_HEAD + NEW_TARGET_TAIL)
    op.create_index(
        "ix_notebooks_owner_id_course_id_student",
        "notebooks",
        ["owner_id", "course_id"],
        unique=True,
        schema="notebooks",
        postgresql_where=sa.text(STUDENT),
    )
    op.create_index(
        "ix_notebooks_course_id_student",
        "notebooks",
        ["course_id"],
        unique=False,
        schema="notebooks",
        postgresql_where=sa.text(STUDENT),
    )


def downgrade() -> None:
    """Downgrade schema (the students' course notebooks are deleted)."""
    op.execute("DELETE FROM notebooks.notebooks WHERE origin = 'course_student'")
    for name in (
        "ix_notebooks_course_id_student",
        "ix_notebooks_owner_id_course_id_student",
    ):
        op.drop_index(
            name,
            table_name="notebooks",
            schema="notebooks",
            postgresql_where=sa.text(STUDENT),
        )
    _replace_check("ck_notebooks_auto_target", TARGET_HEAD + OLD_TARGET_TAIL)
    _replace_check("ck_notebooks_origin", _in_list("origin", OLD_ORIGINS))
    op.alter_column(
        "notebooks",
        "origin",
        schema="notebooks",
        existing_type=sa.String(length=14),
        type_=sa.String(length=12),
        existing_nullable=False,
        existing_server_default=sa.text("'manual'"),
    )
