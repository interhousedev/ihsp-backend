"""admission chooser: the student's bucket and notes on a list entry.

Revision ID: admission_0002
Revises: admission_0001
Create Date: 2026-11-17 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0002"
down_revision: str | Sequence[str] | None = "admission_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the student's own bucket and notes."""
    op.add_column(
        "list_entries",
        sa.Column("bucket", sa.String(length=8), nullable=True),
        schema="admission",
    )
    op.add_column(
        "list_entries",
        sa.Column("notes", sa.String(length=1000), nullable=True),
        schema="admission",
    )


def downgrade() -> None:
    """Drop the columns."""
    op.drop_column("list_entries", "notes", schema="admission")
    op.drop_column("list_entries", "bucket", schema="admission")
