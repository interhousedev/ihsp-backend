"""admission_0048: a planned grade follows the admin school grade range (1–12).

Revision ID: admission_0048_plan_grade_range
Revises: admission_0047_plan_term
Create Date: 2026-11-21 18:00:00.000000

The school grades are an admin setting (``school_grades``, 1–12); the old check
pinned ``opportunity_plan_entries.planned_grade`` to 9–12, which rejected a valid
configured grade below 9. The application validates against the setting.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "admission_0048_plan_grade_range"
down_revision: str | None = "admission_0047_plan_term"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
T = "opportunity_plan_entries"
CK = "ck_opportunity_plan_entries_planned_grade"


def upgrade() -> None:
    """Widen the planned grade check to 1–12."""
    op.drop_constraint(op.f(CK), T, schema=S, type_="check")
    op.create_check_constraint(op.f(CK), T, "planned_grade BETWEEN 1 AND 12", schema=S)


def downgrade() -> None:
    """Restore the 9–12 check (fails if a row holds a grade below 9)."""
    op.drop_constraint(op.f(CK), T, schema=S, type_="check")
    op.create_check_constraint(op.f(CK), T, "planned_grade BETWEEN 9 AND 12", schema=S)
