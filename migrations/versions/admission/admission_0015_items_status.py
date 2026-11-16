"""admission items: draft/ready status, timing and the college intention.

Revision ID: admission_0015_items_status
Revises: admission_0014_tasks
Create Date: 2026-11-16 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0015_items_status"
down_revision: str | Sequence[str] | None = "admission_0014_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"

# Mirrors `Item.missing_for_ready`: honors need a recognition level and grades;
# activities also need the new timing and college intention, so no legacy
# activity qualifies and stays a draft until the student completes it.
_READY = """
UPDATE admission.items SET status = 'ready'
WHERE btrim(position) <> ''
  AND cardinality(grade_levels) > 0
  AND grade_levels <@ ARRAY[9, 10, 11, 12, 13]
  AND (
    (kind = 'honor'
     AND category IN ('school', 'state_regional', 'national', 'international'))
    OR (kind = 'activity'
        AND category IS NOT NULL
        AND btrim(org) <> ''
        AND btrim(description) <> ''
        AND hours_week IS NOT NULL
        AND weeks_year IS NOT NULL
        AND cardinality(timing) > 0
        AND timing <@ ARRAY['school_year', 'school_break', 'all_year']
        AND intend_in_college IS NOT NULL)
  )
"""


def upgrade() -> None:
    """Add the columns, the status check and backfill the status."""
    op.add_column(
        "items",
        sa.Column("status", sa.String(8), server_default="draft", nullable=False),
        schema=S,
    )
    op.add_column(
        "items",
        sa.Column(
            "timing",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        schema=S,
    )
    op.add_column(
        "items", sa.Column("intend_in_college", sa.Boolean(), nullable=True), schema=S
    )
    op.create_check_constraint(
        "status", "items", "status IN ('draft', 'ready')", schema=S
    )
    op.execute(_READY)


def downgrade() -> None:
    """Drop the columns again."""
    op.drop_constraint("ck_items_status", "items", schema=S)
    op.drop_column("items", "intend_in_college", schema=S)
    op.drop_column("items", "timing", schema=S)
    op.drop_column("items", "status", schema=S)
