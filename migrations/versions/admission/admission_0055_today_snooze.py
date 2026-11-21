"""admission today: snoozed next actions.

Revision ID: admission_0055_today_snooze
Revises: admission_0054_essay_ledger
Create Date: 2026-11-21 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0055_today_snooze"
down_revision: str | Sequence[str] | None = "admission_0054_essay_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create today_snoozes."""
    op.create_table(
        "today_snoozes",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("count", sa.SmallInteger(), nullable=False),
        sa.Column("until", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("student_id", "key", name=op.f("pk_today_snoozes")),
        schema=S,
    )


def downgrade() -> None:
    """Drop today_snoozes."""
    op.drop_table("today_snoozes", schema=S)
