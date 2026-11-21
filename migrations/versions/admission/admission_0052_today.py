"""admission today feed: activity days (streak) and season overrides.

Revision ID: admission_0052_today
Revises: admission_0051_task_list_entry
Create Date: 2026-11-21 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0052_today"
down_revision: str | Sequence[str] | None = "admission_0051_task_list_entry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
SEASONS = ("explore", "build", "choose", "write", "submit", "results")


def upgrade() -> None:
    """Create activity_days and season_overrides."""
    op.create_table(
        "activity_days",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("student_id", "day", name=op.f("pk_activity_days")),
        schema=S,
    )
    op.create_table(
        "season_overrides",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=10), nullable=False),
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
        sa.CheckConstraint(
            "key IN (" + ", ".join(repr(s) for s in SEASONS) + ")",
            name=op.f("ck_season_overrides_key"),
        ),
        sa.PrimaryKeyConstraint(
            "student_id", name=op.f("pk_season_overrides")
        ),
        schema=S,
    )


def downgrade() -> None:
    """Drop both tables."""
    op.drop_table("season_overrides", schema=S)
    op.drop_table("activity_days", schema=S)
