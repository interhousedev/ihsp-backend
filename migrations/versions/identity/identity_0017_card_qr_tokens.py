"""Permanent QR tokens of student cards (one per student, replaced on regeneration).

Revision ID: identity_0017
Revises: identity_0016
Create Date: 2026-11-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0017"
down_revision: str | Sequence[str] | None = "identity_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the table; tokens are made on first view of the card."""
    op.create_table(
        "student_card_qr_tokens",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("token", name="uq_student_card_qr_tokens_token"),
        schema="id",
    )


def downgrade() -> None:
    """Drop the table."""
    op.drop_table("student_card_qr_tokens", schema="id")
