"""admission tasks: optional link to the student's list entry.

Revision ID: admission_0051_task_list_entry
Revises: admission_0050_gallery_frozen
Create Date: 2026-11-21 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0051_task_list_entry"
down_revision: str | Sequence[str] | None = "admission_0050_gallery_frozen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Add tasks.list_entry_id."""
    op.add_column(
        "tasks",
        sa.Column("list_entry_id", sa.Uuid(), nullable=True),
        schema=S,
    )
    op.create_foreign_key(
        "fk_tasks_list_entry_id_list_entries",
        "tasks",
        "list_entries",
        ["list_entry_id"],
        ["id"],
        source_schema=S,
        referent_schema=S,
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_admission_tasks_list_entry_id",
        "tasks",
        ["list_entry_id"],
        schema=S,
    )


def downgrade() -> None:
    """Drop tasks.list_entry_id."""
    op.drop_index("ix_admission_tasks_list_entry_id", "tasks", schema=S)
    op.drop_constraint(
        "fk_tasks_list_entry_id_list_entries", "tasks", schema=S, type_="foreignkey"
    )
    op.drop_column("tasks", "list_entry_id", schema=S)
