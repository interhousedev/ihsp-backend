"""Registry of the Telegram bots and the users who wrote to each.

Revision ID: admin_0005
Revises: admin_0004
Create Date: 2026-11-02 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admin_0005"
down_revision: str | Sequence[str] | None = "admin_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    """Create admin.telegram_bots (no token column: tokens live in Vault)."""
    op.create_table(
        "telegram_bots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hint", sa.String(length=8), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_bots")),
        sa.UniqueConstraint("telegram_id", name=op.f("uq_telegram_bots_telegram_id")),
        schema="admin",
    )
    # At most one default bot.
    op.create_index(
        "uq_telegram_bots_default",
        "telegram_bots",
        ["is_default"],
        unique=True,
        schema="admin",
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "telegram_bot_members",
        sa.Column("bot_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["admin.telegram_bots.id"],
            name=op.f("fk_telegram_bot_members_bot_id_telegram_bots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "bot_id", "telegram_user_id", name=op.f("pk_telegram_bot_members")
        ),
        schema="admin",
    )
    op.create_index(
        "ix_telegram_bot_members_user_id",
        "telegram_bot_members",
        ["user_id"],
        schema="admin",
    )


def downgrade() -> None:
    """Drop the registry (the Vault secrets stay; delete them by hand)."""
    op.drop_index(
        "ix_telegram_bot_members_user_id",
        table_name="telegram_bot_members",
        schema="admin",
    )
    op.drop_table("telegram_bot_members", schema="admin")
    op.drop_index(
        "uq_telegram_bots_default", table_name="telegram_bots", schema="admin"
    )
    op.drop_table("telegram_bots", schema="admin")
