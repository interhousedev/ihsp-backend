"""The usage ledger: one row per model call (tokens, cost, who, task, success).

Revision ID: ai_0004
Revises: ai_0003
Create Date: 2026-10-11 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ai_0004"
down_revision: str | Sequence[str] | None = "ai_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = "role IN ('student', 'teacher', 'admin', 'staff', 'system')"


def upgrade() -> None:
    """Create ai.usage_events with its indexes."""
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column(
            "input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "cached_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_micro", sa.BigInteger(), nullable=True),
        sa.Column(
            "success", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("error", sa.String(length=64), nullable=True),
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
        sa.CheckConstraint(ROLES, name=op.f("ck_usage_events_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
        schema="ai",
    )
    op.create_index(
        "ix_usage_events_occurred_at",
        "usage_events",
        ["occurred_at"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "ix_usage_events_user_id_occurred_at",
        "usage_events",
        ["user_id", "occurred_at"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "ix_usage_events_task_occurred_at",
        "usage_events",
        ["task", "occurred_at"],
        unique=False,
        schema="ai",
    )


def downgrade() -> None:
    """Drop the usage ledger."""
    op.drop_index(
        "ix_usage_events_task_occurred_at", table_name="usage_events", schema="ai"
    )
    op.drop_index(
        "ix_usage_events_user_id_occurred_at", table_name="usage_events", schema="ai"
    )
    op.drop_index("ix_usage_events_occurred_at", table_name="usage_events", schema="ai")
    op.drop_table("usage_events", schema="ai")
