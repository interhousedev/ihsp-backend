"""Give the Coach tables created_at and updated_at.

Revision ID: lms_0014
Revises: lms_0013
Create Date: 2026-11-27 14:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "lms_0014_coach_ts"
down_revision: str | Sequence[str] | None = "lms_0013_badge_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "lms.tutor_sessions",
    "lms.tutor_turns",
)


def upgrade() -> None:
    """Add the missing created_at / updated_at columns."""
    for table in _TABLES:
        for column in ("created_at", "updated_at"):
            op.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} "
                "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()"
            )


def downgrade() -> None:
    """Drop the updated_at columns (created_at may predate this revision)."""
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS updated_at")
