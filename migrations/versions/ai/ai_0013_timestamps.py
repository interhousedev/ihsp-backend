"""ai: timestamps on ai_requests and prompt_defaults.

Revision ID: ai_0013
Revises: ai_0012
Create Date: 2026-11-21 23:59:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ai_0013"
down_revision: str | Sequence[str] | None = "ai_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add(table: str, column: str, schema: str) -> None:
    op.add_column(
        table,
        sa.Column(
            column,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema=schema,
    )


def upgrade() -> None:
    """Add the missing timestamps."""
    _add("ai_requests", "created_at", "ai")
    _add("ai_requests", "updated_at", "ai")
    _add("prompt_defaults", "created_at", "ai")


def downgrade() -> None:
    """Drop the added timestamps."""
    op.drop_column("prompt_defaults", "created_at", schema="ai")
    op.drop_column("ai_requests", "updated_at", schema="ai")
    op.drop_column("ai_requests", "created_at", schema="ai")
