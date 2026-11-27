"""Teacher-written solution keys of the Coach, stored with the step revision.

Revision ID: lms_0011_solution_keys
Revises: lms_0010_coach
Create Date: 2026-11-27 10:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "lms_0011_solution_keys"
down_revision: str | Sequence[str] | None = "lms_0010_coach"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the keys column."""
    op.add_column(
        "step_revisions",
        sa.Column(
            "solution_keys",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        schema="lms",
    )


def downgrade() -> None:
    """Drop the keys column."""
    op.drop_column("step_revisions", "solution_keys", schema="lms")
