"""Coach: tutoring sessions and their turns.

Revision ID: lms_0010_coach
Revises: lms_0009_badges
Create Date: 2026-11-27 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "lms_0010_coach"
down_revision: str | Sequence[str] | None = "lms_0009_badges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the session and turn tables."""
    op.create_table(
        "tutor_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=True),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=True),
        sa.Column("revision_id", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column(
            "hint_level", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mode IN ('ask', 'hint', 'remediate', 'recap')",
            name=op.f("ck_tutor_sessions_mode"),
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('resolved', 'abandoned', 'escalated')",
            name=op.f("ck_tutor_sessions_outcome"),
        ),
        sa.CheckConstraint(
            "hint_level BETWEEN 0 AND 3", name=op.f("ck_tutor_sessions_hint_level")
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["lms.course_steps.id"],
            name=op.f("fk_tutor_sessions_step_id_course_steps"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_sessions")),
        schema="lms",
    )
    op.create_index(
        "ix_tutor_sessions_user_id_step_id",
        "tutor_sessions",
        ["user_id", "step_id"],
        schema="lms",
    )
    op.create_index(
        "ix_tutor_sessions_step_id_opened_at",
        "tutor_sessions",
        ["step_id", "opened_at"],
        schema="lms",
    )
    op.create_table(
        "tutor_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "hint_level", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "citations",
            postgresql.ARRAY(sa.String()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('learner', 'tutor')", name=op.f("ck_tutor_turns_role")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["lms.tutor_sessions.id"],
            name=op.f("fk_tutor_turns_session_id_tutor_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tutor_turns")),
        schema="lms",
    )
    op.create_index(
        "ix_tutor_turns_session_id_created_at",
        "tutor_turns",
        ["session_id", "created_at"],
        schema="lms",
    )


def downgrade() -> None:
    """Drop the tables."""
    op.drop_table("tutor_turns", schema="lms")
    op.drop_table("tutor_sessions", schema="lms")
