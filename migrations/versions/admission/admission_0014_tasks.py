"""admission tasks: assignable tasks with steps and links.

Revision ID: admission_0014_tasks
Revises: admission_0013_programs
Create Date: 2026-11-22 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0014_tasks"
down_revision: str | Sequence[str] | None = "admission_0013_programs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def _ts(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _json(name: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )


def upgrade() -> None:
    """Create the tasks table."""
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "status", sa.String(length=11), server_default="planned", nullable=False
        ),
        sa.Column(
            "priority", sa.String(length=6), server_default="medium", nullable=False
        ),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column(
            "created_by", sa.String(length=10), server_default="student", nullable=False
        ),
        sa.Column("creator_id", sa.Uuid(), nullable=True),
        _json("steps"),
        _json("links"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("lock_version", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'in_review', 'blocked', 'done')",
            name=op.f("ck_tasks_status"),
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high')", name=op.f("ck_tasks_priority")
        ),
        sa.CheckConstraint(
            "created_by IN ('student', 'mentor', 'counselor', 'ai')",
            name=op.f("ck_tasks_created_by"),
        ),
        sa.CheckConstraint(
            "start_date IS NULL OR start_date >= DATE '2000-01-01'",
            name=op.f("ck_tasks_start_year"),
        ),
        sa.CheckConstraint(
            "deadline IS NULL OR deadline >= DATE '2000-01-01'",
            name=op.f("ck_tasks_deadline_year"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_tasks_student_id"), "tasks", ["student_id"], schema=S
    )


def downgrade() -> None:
    """Drop the tasks table."""
    op.drop_table("tasks", schema=S)
