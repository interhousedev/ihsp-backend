"""The per-course switch of the "Ask about this lesson" tutor.

Revision ID: lms_0006_tutor
Revises: lms_0005
Create Date: 2026-11-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "lms_0006_tutor"
down_revision: str | Sequence[str] | None = "lms_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add lms.courses.tutor_enabled (on for every existing course)."""
    op.add_column(
        "courses",
        sa.Column(
            "tutor_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        schema="lms",
    )


def downgrade() -> None:
    """Drop the column."""
    op.drop_column("courses", "tutor_enabled", schema="lms")
