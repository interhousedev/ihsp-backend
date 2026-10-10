"""course broadcast updated_at

Revision ID: notify_0007
Revises: notify_0006
Create Date: 2026-10-10 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notify_0007"
down_revision: str | Sequence[str] | None = "notify_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Mark edited broadcasts: ``updated_at`` stays NULL until the first edit."""
    op.add_column(
        "course_broadcasts",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="notify",
    )


def downgrade() -> None:
    """Drop the edit marker."""
    op.drop_column("course_broadcasts", "updated_at", schema="notify")
