"""admission timestamps: updated_at / created_at on the tables that lacked one.

Revision ID: admission_0019_timestamps
Revises: admission_0018_assistant
Create Date: 2026-11-24 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0019_timestamps"
down_revision: str | Sequence[str] | None = "admission_0018_assistant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
UPDATED = (
    "assistant_messages",
    "opportunity_taxonomy",
    "opportunity_plan_entries",
    "opportunity_ai_plans",
)


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    """Add the missing timestamp columns."""
    for table in UPDATED:
        op.add_column(
            table,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=_now(),
                nullable=False,
            ),
            schema=S,
        )
    op.add_column(
        "admission_student_chunks",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_now(),
            nullable=False,
        ),
        schema=S,
    )


def downgrade() -> None:
    """Drop the columns."""
    op.drop_column("admission_student_chunks", "created_at", schema=S)
    for table in reversed(UPDATED):
        op.drop_column(table, "updated_at", schema=S)
