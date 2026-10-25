"""Attendance late list: students who came late count as present.

Revision ID: academic_0004
Revises: academic_0003
Create Date: 2026-10-10 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0004"
down_revision: str | Sequence[str] | None = "academic_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the late list next to the absent list."""
    op.add_column(
        "lessons",
        sa.Column("attendance_late", sa.ARRAY(sa.Uuid()), nullable=True),
        schema="academic",
    )
    op.create_check_constraint(
        op.f("ck_lessons_attendance_late_subset"),
        "lessons",
        "attendance_late <@ attendance_roster",
        schema="academic",
    )
    op.create_check_constraint(
        op.f("ck_lessons_attendance_late_not_absent"),
        "lessons",
        "NOT (attendance_late && attendance_absent)",
        schema="academic",
    )


def downgrade() -> None:
    """Drop the late list."""
    op.drop_constraint(
        op.f("ck_lessons_attendance_late_not_absent"),
        "lessons",
        schema="academic",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_lessons_attendance_late_subset"),
        "lessons",
        schema="academic",
        type_="check",
    )
    op.drop_column("lessons", "attendance_late", schema="academic")
