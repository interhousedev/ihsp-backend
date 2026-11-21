"""admission: updated_at on the tables that lacked it.

Revision ID: admission_0057_updated_at
Revises: admission_0056_staff_pin
Create Date: 2026-11-21 23:59:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0057_updated_at"
down_revision: str | Sequence[str] | None = "admission_0056_staff_pin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add(table: str, column: str, schema: str) -> None:
    op.add_column(
        table,
        sa.Column(
            column,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema=schema,
    )


def upgrade() -> None:
    """Add the missing timestamps."""
    _add("essay_gallery", "updated_at", "admission")
    _add("prompt_group_labels", "updated_at", "admission")
    _add("idea_fits", "updated_at", "admission")
    _add("honor_dismissals", "updated_at", "admission")
    _add("activity_days", "updated_at", "admission")


def downgrade() -> None:
    """Drop the added timestamps."""
    op.drop_column("essay_gallery", "updated_at", schema="admission")
    op.drop_column("prompt_group_labels", "updated_at", schema="admission")
    op.drop_column("idea_fits", "updated_at", schema="admission")
    op.drop_column("honor_dismissals", "updated_at", schema="admission")
    op.drop_column("activity_days", "updated_at", schema="admission")
