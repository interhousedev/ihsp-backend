"""Index the AI review sessions by student for the learning record.

Revision ID: lms_0015
Revises: lms_0014
Create Date: 2026-11-28 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "lms_0015_ai_review_user"
down_revision: str | Sequence[str] | None = "lms_0014_coach_ts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ix_ai_review_sessions_user (user_id, id)."""
    op.create_index(
        "ix_ai_review_sessions_user",
        "ai_review_sessions",
        ["user_id", "id"],
        unique=False,
        schema="lms",
    )


def downgrade() -> None:
    """Drop the index."""
    op.drop_index(
        "ix_ai_review_sessions_user", table_name="ai_review_sessions", schema="lms"
    )
