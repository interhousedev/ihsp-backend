"""Usage analytics: request, pipeline, connector and size columns on the ledger.

Revision ID: ai_0012
Revises: ai_0011
Create Date: 2026-12-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ai_0012"
down_revision: str | Sequence[str] | None = "ai_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the analytics columns and the per-request index."""
    op.add_column(
        "usage_events",
        sa.Column("request_id", sa.String(length=96), nullable=True),
        schema="ai",
    )
    op.add_column(
        "usage_events",
        sa.Column("pipeline", sa.String(length=32), nullable=True),
        schema="ai",
    )
    op.add_column(
        "usage_events",
        sa.Column("connector_id", sa.String(length=48), nullable=True),
        schema="ai",
    )
    op.add_column(
        "usage_events",
        sa.Column("prompt_chars", sa.Integer(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "usage_events",
        sa.Column("prompt_tokens_est", sa.Integer(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "usage_events",
        sa.Column("answer_chars", sa.Integer(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "usage_events",
        sa.Column(
            "tool_calls",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema="ai",
    )
    op.create_index(
        "ix_usage_events_request_occurred_at",
        "usage_events",
        ["request_id", "occurred_at"],
        unique=False,
        schema="ai",
    )


def downgrade() -> None:
    """Drop the analytics columns and their index."""
    op.drop_index(
        "ix_usage_events_request_occurred_at",
        table_name="usage_events",
        schema="ai",
    )
    for column in (
        "tool_calls",
        "answer_chars",
        "prompt_tokens_est",
        "prompt_chars",
        "connector_id",
        "pipeline",
        "request_id",
    ):
        op.drop_column("usage_events", column, schema="ai")
