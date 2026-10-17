"""Attendance from EMIS per student, subject and semester.

Revision ID: academic_0006
Revises: academic_0005
Create Date: 2026-10-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "academic_0006"
down_revision: str | Sequence[str] | None = "academic_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create emis_attendance."""
    op.create_table(
        "emis_attendance",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("semester", sa.SmallInteger(), nullable=False),
        sa.Column("absent_dates", postgresql.ARRAY(sa.Date()), nullable=True),
        sa.Column("absence_total", sa.Integer(), nullable=True),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["academic.students.user_id"],
            name=op.f("fk_emis_attendance_student_id_students"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["academic.subjects.id"],
            name=op.f("fk_emis_attendance_subject_id_subjects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "student_id", "subject_id", "semester", name=op.f("pk_emis_attendance")
        ),
        schema="academic",
    )


def downgrade() -> None:
    """Drop emis_attendance."""
    op.drop_table("emis_attendance", schema="academic")
