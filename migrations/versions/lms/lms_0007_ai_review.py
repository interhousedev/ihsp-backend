"""AI review conversations of students (the ai_review block).

Revision ID: lms_0007_ai_review
Revises: lms_0006_tutor
Create Date: 2026-11-23 12:00:00.000000

"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "lms_0007_ai_review"
down_revision: str | Sequence[str] | None = "lms_0006_tutor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[datetime]]:
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
    """Create lms.ai_review_sessions and lms.ai_review_messages."""
    op.create_table(
        "ai_review_sessions",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column(
            "submissions_used",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('open', 'reviewed')",
            name=op.f("ck_ai_review_sessions_status"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_ai_review_sessions_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_review_sessions")),
        schema="lms",
    )
    op.create_index(
        "ix_ai_review_sessions_block",
        "ai_review_sessions",
        ["step_id", "block_id", "user_id"],
        unique=False,
        schema="lms",
    )
    op.create_table(
        "ai_review_messages",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("openui", sa.Text(), nullable=True),
        sa.Column("history", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "attachments",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "kind IN ('chat', 'question', 'review')",
            name=op.f("ck_ai_review_messages_kind"),
        ),
        sa.CheckConstraint(
            "role IN ('student', 'assistant')",
            name=op.f("ck_ai_review_messages_role"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["lms.ai_review_sessions.id"],
            name=op.f("fk_ai_review_messages_session_id_ai_review_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_review_messages")),
        schema="lms",
    )
    op.create_index(
        op.f("ix_lms_ai_review_messages_session_id"),
        "ai_review_messages",
        ["session_id"],
        unique=False,
        schema="lms",
    )


def downgrade() -> None:
    """Drop the AI review tables."""
    op.drop_table("ai_review_messages", schema="lms")
    op.drop_table("ai_review_sessions", schema="lms")
