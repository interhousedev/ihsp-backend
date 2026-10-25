"""Durable state of each student's initial EMIS sync (sync with proof).

Revision ID: academic_0007
Revises: academic_0006
Create Date: 2026-10-18 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0007"
down_revision: str | Sequence[str] | None = "academic_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create student_sync_jobs: one row per student, written with the registration."""
    op.create_table(
        "student_sync_jobs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("subgroup", sa.SmallInteger(), nullable=True),
        sa.Column("marks_count", sa.Integer(), nullable=True),
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
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name=op.f("ck_student_sync_jobs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["academic.students.user_id"],
            name=op.f("fk_student_sync_jobs_user_id_students"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_student_sync_jobs")),
        schema="academic",
    )
    op.create_index(
        "ix_student_sync_jobs_status_next_attempt",
        "student_sync_jobs",
        ["status", "next_attempt_at"],
        schema="academic",
    )


def downgrade() -> None:
    """Drop student_sync_jobs."""
    op.drop_index(
        "ix_student_sync_jobs_status_next_attempt",
        table_name="student_sync_jobs",
        schema="academic",
    )
    op.drop_table("student_sync_jobs", schema="academic")
