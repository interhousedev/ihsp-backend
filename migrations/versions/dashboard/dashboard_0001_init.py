"""dashboard init.

Revision ID: dashboard_0001
Revises:
Create Date: 2026-10-10 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "dashboard_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("dashboard",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS dashboard")
    op.create_table(
        "layouts",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("widgets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_layouts")),
        schema="dashboard",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("layouts", schema="dashboard")
    op.execute("DROP SCHEMA IF EXISTS dashboard")
