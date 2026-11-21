"""ai: Langfuse tracing per pipeline and the runtime Langfuse project.

Revision ID: ai_0014
Revises: ai_0013
Create Date: 2026-11-21 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ai_0014"
down_revision: str | Sequence[str] | None = "ai_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    """Add the tracing switches to the routes and the single settings row table."""
    op.add_column(
        "pipeline_routes",
        sa.Column("tracing_enabled", sa.Boolean(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "pipeline_routes",
        sa.Column("capture_content", sa.Boolean(), nullable=True),
        schema="ai",
    )
    op.create_table(
        "tracing_settings",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("host", sa.String(length=500), nullable=False),
        sa.Column("public_key", sa.String(length=255), nullable=False),
        sa.Column(
            "has_secret", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("secret_last4", sa.String(length=4), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_NOW,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=_NOW,
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_tracing_settings_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tracing_settings")),
        schema="ai",
    )


def downgrade() -> None:
    """Drop the table and the switches."""
    op.drop_table("tracing_settings", schema="ai")
    op.drop_column("pipeline_routes", "capture_content", schema="ai")
    op.drop_column("pipeline_routes", "tracing_enabled", schema="ai")
