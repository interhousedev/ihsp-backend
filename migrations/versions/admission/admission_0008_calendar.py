"""admission calendar: private ICS feeds, the reminder ledger and exam dates.

Revision ID: admission_0008
Revises: admission_0006
Create Date: 2026-11-20 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0008"
down_revision: str | Sequence[str] | None = "admission_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    """Create calendar_feeds, calendar_reminders and exam_dates."""
    op.create_table(
        "calendar_feeds",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("locale", sa.String(length=5), nullable=False),
        sa.Column(
            "alarm_offsets", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_feeds")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_calendar_feeds_token_hash")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_calendar_feeds_user_id"),
        "calendar_feeds",
        ["user_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "calendar_reminders",
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        *_stamps(),
        sa.PrimaryKeyConstraint("dedupe_key", name=op.f("pk_calendar_reminders")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_calendar_reminders_user_id"),
        "calendar_reminders",
        ["user_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "exam_dates",
        sa.Column("exam", sa.String(length=10), nullable=False),
        sa.Column("test_date", sa.Date(), nullable=False),
        sa.Column("registration_deadline", sa.Date(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.CheckConstraint(
            "exam IN ('ielts', 'toefl', 'duolingo', 'sat', 'act')",
            name=op.f("ck_exam_dates_exam"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_dates")),
        schema="admission",
    )


def downgrade() -> None:
    """Drop the calendar tables."""
    op.drop_table("exam_dates", schema="admission")
    op.drop_index(
        op.f("ix_admission_calendar_reminders_user_id"),
        table_name="calendar_reminders",
        schema="admission",
    )
    op.drop_table("calendar_reminders", schema="admission")
    op.drop_index(
        op.f("ix_admission_calendar_feeds_user_id"),
        table_name="calendar_feeds",
        schema="admission",
    )
    op.drop_table("calendar_feeds", schema="admission")
