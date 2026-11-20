"""AI connectors and pipeline routes: ai.connectors, ai.pipeline_routes.

Revision ID: ai_0010_connectors_pipelines
Revises: ai_0009
Create Date: 2026-11-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ai_0010_connectors_pipelines"
down_revision: str | Sequence[str] | None = "ai_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    """Create the two tables (empty: the environment's connectors need no rows)."""
    op.create_table(
        "connectors",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "has_secret", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("secret_last4", sa.String(length=4), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint(
            "kind IN ('openrouter', 'anthropic', 'openai_compatible', 'exa')",
            name=op.f("ck_connectors_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connectors")),
        schema="ai",
    )
    op.create_table(
        "pipeline_routes",
        sa.Column("pipeline", sa.String(length=32), nullable=False),
        sa.Column("connector_id", sa.String(length=48), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("reasoning_effort", sa.String(length=16), nullable=True),
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
        sa.CheckConstraint(
            "reasoning_effort IS NULL OR "
            "reasoning_effort IN ('none', 'minimal', 'low', 'medium', 'high')",
            name=op.f("ck_pipeline_routes_reasoning_effort"),
        ),
        sa.PrimaryKeyConstraint("pipeline", name=op.f("pk_pipeline_routes")),
        schema="ai",
    )


def downgrade() -> None:
    """Drop the two tables."""
    op.drop_table("pipeline_routes", schema="ai")
    op.drop_table("connectors", schema="ai")
