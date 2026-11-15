"""Telegram topics: one forum topic of a private chat per AI chat.

Revision ID: ai_0007
Revises: ai_0006
Create Date: 2026-11-15 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ai_0007"
down_revision: str | Sequence[str] | None = "ai_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ai.telegram_topics."""
    op.create_table(
        "telegram_topics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("message_thread_id", sa.Integer(), nullable=False),
        sa.Column(
            "title", sa.String(length=128), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("icon_custom_emoji_id", sa.String(length=64), nullable=True),
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
            ["chat_id"],
            ["ai.chats.id"],
            name=op.f("fk_telegram_topics_chat_id_chats"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_topics")),
        schema="ai",
    )
    op.create_index(
        "ux_telegram_topics_chat_id",
        "telegram_topics",
        ["chat_id"],
        unique=True,
        schema="ai",
    )
    op.create_index(
        "ux_telegram_topics_thread",
        "telegram_topics",
        ["telegram_chat_id", "message_thread_id"],
        unique=True,
        schema="ai",
    )


def downgrade() -> None:
    """Drop ai.telegram_topics."""
    op.drop_index(
        "ux_telegram_topics_thread", table_name="telegram_topics", schema="ai"
    )
    op.drop_index(
        "ux_telegram_topics_chat_id", table_name="telegram_topics", schema="ai"
    )
    op.drop_table("telegram_topics", schema="ai")
