"""Add updated_at to academic.curriculum_topics.

Revision ID: academic_0018
Revises: academic_0017
Create Date: 2026-11-27 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0018"
down_revision: str | Sequence[str] | None = "academic_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the updated_at column."""
    op.add_column(
        "curriculum_topics",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="academic",
    )


def downgrade() -> None:
    """Drop the updated_at column."""
    op.drop_column("curriculum_topics", "updated_at", schema="academic")
