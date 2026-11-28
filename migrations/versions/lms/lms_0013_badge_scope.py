"""Platform badges: scope, nullable course, template and rule version.

Revision ID: lms_0013_badge_scope
Revises: lms_0012_levels
Create Date: 2026-11-27 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "lms_0013_badge_scope"
down_revision: str | Sequence[str] | None = "lms_0012_levels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the badge scope columns and let platform rows have no course."""
    op.add_column(
        "badges",
        sa.Column(
            "scope", sa.String(16), server_default=sa.text("'course'"), nullable=False
        ),
        schema="lms",
    )
    op.add_column("badges", sa.Column("template_code", sa.String(32)), schema="lms")
    op.add_column(
        "badges",
        sa.Column("template_params", postgresql.JSONB(astext_type=sa.Text())),
        schema="lms",
    )
    op.add_column(
        "badges",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        schema="lms",
    )
    op.alter_column("badges", "course_id", nullable=True, schema="lms")
    op.alter_column("badge_awards", "course_id", nullable=True, schema="lms")
    op.create_check_constraint(
        "scope_course",
        "badges",
        "(scope = 'course' AND course_id IS NOT NULL) "
        "OR (scope = 'platform' AND course_id IS NULL)",
        schema="lms",
    )


def downgrade() -> None:
    """Remove platform badges and the scope columns."""
    op.execute("DELETE FROM lms.badges WHERE scope = 'platform'")
    op.drop_constraint("ck_badges_scope_course", "badges", schema="lms")
    op.alter_column("badge_awards", "course_id", nullable=False, schema="lms")
    op.alter_column("badges", "course_id", nullable=False, schema="lms")
    for column in ("version", "template_params", "template_code", "scope"):
        op.drop_column("badges", column, schema="lms")
