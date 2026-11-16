"""admission checklist: one row per student, list entry and template.

Revision ID: admission_0005
Revises: admission_0004
Create Date: 2026-11-18 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0005"
down_revision: str | Sequence[str] | None = "admission_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Make checklist generation idempotent at the database level."""
    op.create_index(
        "uq_checklist_items_template",
        "checklist_items",
        ["student_id", "list_entry_id", "template_key"],
        unique=True,
        schema="admission",
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    """Drop the index."""
    op.drop_index("uq_checklist_items_template", "checklist_items", schema="admission")
