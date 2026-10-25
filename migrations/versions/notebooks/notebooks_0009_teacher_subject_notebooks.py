"""Subject notebooks of teachers: one per subject and group.

A teacher's subject notebook is scoped to a group (`group_id`); a student's has none.
The student unique index now ignores group notebooks, a second one covers teachers.

Revision ID: notebooks_0009
Revises: notebooks_0008
Create Date: 2026-10-12 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0009"
down_revision: str | Sequence[str] | None = "notebooks_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STUDENT_WHERE = "origin = 'subject_auto' AND deleted_at IS NULL"
STUDENT_WHERE_NEW = (
    "origin = 'subject_auto' AND group_id IS NULL AND deleted_at IS NULL"
)
TEACHER_WHERE = (
    "origin = 'subject_auto' AND group_id IS NOT NULL AND deleted_at IS NULL"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "notebooks",
        sa.Column("group_id", sa.Uuid(), nullable=True),
        schema="notebooks",
    )
    op.create_check_constraint(
        op.f("ck_notebooks_group_subject_only"),
        "notebooks",
        "group_id IS NULL OR origin = 'subject_auto'",
        schema="notebooks",
    )
    op.drop_index(
        "ix_notebooks_owner_id_subject_id_auto",
        table_name="notebooks",
        schema="notebooks",
    )
    op.create_index(
        "ix_notebooks_owner_id_subject_id_auto",
        "notebooks",
        ["owner_id", "subject_id"],
        unique=True,
        schema="notebooks",
        postgresql_where=sa.text(STUDENT_WHERE_NEW),
    )
    op.create_index(
        "ix_notebooks_owner_id_subject_id_group_id_auto",
        "notebooks",
        ["owner_id", "subject_id", "group_id"],
        unique=True,
        schema="notebooks",
        postgresql_where=sa.text(TEACHER_WHERE),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_notebooks_owner_id_subject_id_group_id_auto",
        table_name="notebooks",
        schema="notebooks",
    )
    op.drop_index(
        "ix_notebooks_owner_id_subject_id_auto",
        table_name="notebooks",
        schema="notebooks",
    )
    op.execute("DELETE FROM notebooks.notebooks WHERE group_id IS NOT NULL")
    op.create_index(
        "ix_notebooks_owner_id_subject_id_auto",
        "notebooks",
        ["owner_id", "subject_id"],
        unique=True,
        schema="notebooks",
        postgresql_where=sa.text(STUDENT_WHERE),
    )
    op.drop_constraint(
        op.f("ck_notebooks_group_subject_only"),
        "notebooks",
        schema="notebooks",
        type_="check",
    )
    op.drop_column("notebooks", "group_id", schema="notebooks")
