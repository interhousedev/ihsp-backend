"""admission goal plan: a milestone's due month is the first day of its month.

Revision ID: admission_0003
Revises: admission_0002
Create Date: 2026-11-16 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0003"
down_revision: str | Sequence[str] | None = "admission_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Normalise stored months and forbid any other day."""
    op.execute(
        "UPDATE admission.goal_milestones "
        "SET due_month = date_trunc('month', due_month)::date "
        "WHERE due_month IS NOT NULL"
    )
    op.create_check_constraint(
        op.f("ck_goal_milestones_due_month_first_day"),
        "goal_milestones",
        "due_month IS NULL OR extract(day FROM due_month) = 1",
        schema="admission",
    )


def downgrade() -> None:
    """Drop the constraint."""
    op.drop_constraint(
        op.f("ck_goal_milestones_due_month_first_day"),
        "goal_milestones",
        schema="admission",
        type_="check",
    )
