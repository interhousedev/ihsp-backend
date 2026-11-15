"""Audience rules of courses and lessons.

Revision ID: lms_0005
Revises: lms_0004
Create Date: 2026-11-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "lms_0005"
down_revision: str | Sequence[str] | None = "lms_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create lms.access_rules; no row means the item is public."""
    op.create_table(
        "access_rules",
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column(
            "audience",
            sa.String(length=16),
            server_default=sa.text("'public'"),
            nullable=False,
        ),
        sa.Column(
            "when_denied",
            sa.String(length=16),
            server_default=sa.text("'hidden'"),
            nullable=False,
        ),
        sa.Column(
            "group_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "user_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
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
            "audience IN ('public', 'signed_in', 'students', 'chosen')",
            name=op.f("ck_access_rules_audience"),
        ),
        sa.CheckConstraint(
            "when_denied IN ('hidden', 'locked')",
            name=op.f("ck_access_rules_when_denied"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_access_rules_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("target_id", name=op.f("pk_access_rules")),
        schema="lms",
    )
    op.create_index(
        "ix_access_rules_course_id",
        "access_rules",
        ["course_id"],
        unique=False,
        schema="lms",
    )


def downgrade() -> None:
    """Drop lms.access_rules."""
    op.drop_index("ix_access_rules_course_id", table_name="access_rules", schema="lms")
    op.drop_table("access_rules", schema="lms")
