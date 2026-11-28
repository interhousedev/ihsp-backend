"""Give id.student_card_qr_tokens the updated_at column every table has.

Revision ID: identity_0019
Revises: identity_0018
Create Date: 2026-11-28 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0019"
down_revision: str | Sequence[str] | None = "identity_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add updated_at, filled with now() for the existing rows."""
    op.add_column(
        "student_card_qr_tokens",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="id",
    )


def downgrade() -> None:
    """Drop updated_at."""
    op.drop_column("student_card_qr_tokens", "updated_at", schema="id")
