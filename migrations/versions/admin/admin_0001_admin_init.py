"""admin init

Revision ID: admin_0001
Revises:
Create Date: 2026-10-07 17:00:42.405041

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admin_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("admin",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS admin")
    op.create_table(
        "broadcasts",
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_via",
            sa.Enum(
                "ui",
                "assistant",
                name="created_via",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "media_file_ids",
            sa.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("audience", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "scheduled",
                "sending",
                "sent",
                "cancelled",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broadcasts")),
        schema="admin",
    )
    op.create_index(
        "ix_broadcasts_media_file_ids",
        "broadcasts",
        ["media_file_ids"],
        unique=False,
        schema="admin",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_broadcasts_status_scheduled_at",
        "broadcasts",
        ["status", "scheduled_at"],
        unique=False,
        schema="admin",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_broadcasts_status_scheduled_at", table_name="broadcasts", schema="admin"
    )
    op.drop_index(
        "ix_broadcasts_media_file_ids",
        table_name="broadcasts",
        schema="admin",
        postgresql_using="gin",
    )
    op.drop_table("broadcasts", schema="admin")
    op.execute("DROP SCHEMA IF EXISTS admin CASCADE")
