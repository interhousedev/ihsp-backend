"""Add academic.groups.hidden (admins hide a group without deleting it).

Revision ID: academic_0019
Revises: academic_0018
Create Date: 2026-11-28 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0019"
down_revision: str | Sequence[str] | None = "academic_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the hidden flag."""
    op.add_column(
        "groups",
        sa.Column(
            "hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        schema="academic",
    )


def downgrade() -> None:
    """Drop the hidden flag."""
    op.drop_column("groups", "hidden", schema="academic")
