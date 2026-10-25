"""Per-user extensions of the AI limits.

Revision ID: admin_0003
Revises: admin_0002
Create Date: 2026-10-11 09:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admin_0003"
down_revision: str | Sequence[str] | None = "admin_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create admin.limit_extensions: one row per student who has an extension."""
    op.create_table(
        "limit_extensions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("multiplier", sa.SmallInteger(), nullable=True),
        sa.Column(
            "values",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column(
            "note", sa.String(length=500), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint(
            "multiplier IS NULL OR multiplier BETWEEN 2 AND 10",
            name=op.f("ck_limit_extensions_multiplier"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_limit_extensions")),
        schema="admin",
    )


def downgrade() -> None:
    """Drop the extensions."""
    op.drop_table("limit_extensions", schema="admin")
