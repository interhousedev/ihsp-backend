"""Editable prompts: ai.prompt_versions, and the prompt version on calls and replies.

Revision ID: ai_0008
Revises: ai_0007
Create Date: 2026-11-20 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ai_0008"
down_revision: str | Sequence[str] | None = "ai_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ai.prompt_versions; add the prompt columns to the ledger and messages."""
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "locale", sa.String(length=8), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("hash", sa.String(length=16), nullable=False),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "note", sa.String(length=500), server_default=sa.text("''"), nullable=False
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_versions")),
        sa.UniqueConstraint(
            "task",
            "name",
            "locale",
            "version",
            name=op.f("uq_prompt_versions_slot_version"),
        ),
        schema="ai",
    )
    op.create_index(
        "ux_prompt_versions_active",
        "prompt_versions",
        ["task", "name", "locale"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("active"),
    )
    op.create_index(
        "ix_prompt_versions_task_version",
        "prompt_versions",
        ["task", "version"],
        schema="ai",
    )
    op.add_column(
        "usage_events",
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "usage_events",
        sa.Column("prompt_hash", sa.String(length=16), nullable=True),
        schema="ai",
    )
    op.add_column(
        "usage_events",
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "chat_messages",
        sa.Column("prompt_task", sa.String(length=64), nullable=True),
        schema="ai",
    )
    op.add_column(
        "chat_messages",
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        schema="ai",
    )


def downgrade() -> None:
    """Drop the prompt columns and ai.prompt_versions."""
    op.drop_column("chat_messages", "prompt_version", schema="ai")
    op.drop_column("chat_messages", "prompt_task", schema="ai")
    op.drop_column("usage_events", "latency_ms", schema="ai")
    op.drop_column("usage_events", "prompt_hash", schema="ai")
    op.drop_column("usage_events", "prompt_version", schema="ai")
    op.drop_index(
        "ix_prompt_versions_task_version", table_name="prompt_versions", schema="ai"
    )
    op.drop_index(
        "ux_prompt_versions_active", table_name="prompt_versions", schema="ai"
    )
    op.drop_table("prompt_versions", schema="ai")
