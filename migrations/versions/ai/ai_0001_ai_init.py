"""ai init

Revision ID: ai_0001
Revises:
Create Date: 2026-10-07 17:00:59.778460

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ai_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("ai",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Schema ai is shared with the flashcards branch, which may be upgraded first.
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")
    op.create_table(
        "chats",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "assistant",
            sa.Enum(
                "student",
                "admin",
                name="assistant",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "pending_approvals",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chats")),
        schema="ai",
    )
    op.create_index(
        "ix_chats_owner_id_last_message_at",
        "chats",
        ["owner_id", "last_message_at"],
        unique=False,
        schema="ai",
    )
    op.create_table(
        "chat_messages",
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "assistant",
                name="role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "file_ids",
            sa.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["chat_id"],
            ["ai.chats.id"],
            name=op.f("fk_chat_messages_chat_id_chats"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        sa.UniqueConstraint("chat_id", "seq", name="uq_chat_messages_chat_id_seq"),
        schema="ai",
    )
    op.create_index(
        "ix_chat_messages_file_ids",
        "chat_messages",
        ["file_ids"],
        unique=False,
        schema="ai",
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_chat_messages_file_ids",
        table_name="chat_messages",
        schema="ai",
        postgresql_using="gin",
    )
    op.drop_table("chat_messages", schema="ai")
    op.drop_index("ix_chats_owner_id_last_message_at", table_name="chats", schema="ai")
    op.drop_table("chats", schema="ai")
    # Shared with the flashcards branch: drop the schema only when nothing is left.
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS "
        "(SELECT 1 FROM pg_tables WHERE schemaname = 'ai') "
        "THEN DROP SCHEMA IF EXISTS ai; END IF; END $$"
    )
