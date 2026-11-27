"""Level schemes, the learners' high-water marks and the coach XP source.

Revision ID: lms_0012_levels
Revises: lms_0011_solution_keys
Create Date: 2026-11-27 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "lms_0012_levels"
down_revision: str | Sequence[str] | None = "lms_0011_solution_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SOURCES = "source IN ('step', 'test', 'review', 'quest', 'exam', 'widget')"
NEW_SOURCES = "source IN ('step', 'test', 'review', 'quest', 'exam', 'widget', 'coach')"


def _stamps() -> list[sa.Column]:
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
    """Create the level tables and let the coach earn XP."""
    op.create_table(
        "level_schemes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=True),
        sa.Column("name", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("curve", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tiers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        *_stamps(),
        sa.CheckConstraint(
            "scope IN ('platform', 'course')", name=op.f("ck_level_schemes_scope")
        ),
        sa.CheckConstraint(
            "(scope = 'course') = (course_id IS NOT NULL)",
            name=op.f("ck_level_schemes_scope_course"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_level_schemes_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_level_schemes")),
        schema="lms",
    )
    op.create_index(
        "uq_level_schemes_active_platform",
        "level_schemes",
        ["scope"],
        unique=True,
        schema="lms",
        postgresql_where=sa.text("active AND scope = 'platform'"),
    )
    op.create_index(
        "uq_level_schemes_active_course",
        "level_schemes",
        ["course_id"],
        unique=True,
        schema="lms",
        postgresql_where=sa.text("active AND scope = 'course'"),
    )
    op.create_table(
        "level_marks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=True),
        sa.Column("level", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_stamps(),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_level_marks_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_level_marks")),
        schema="lms",
    )
    op.create_index(
        "uq_level_marks_user_platform",
        "level_marks",
        ["user_id"],
        unique=True,
        schema="lms",
        postgresql_where=sa.text("course_id IS NULL"),
    )
    op.create_index(
        "uq_level_marks_user_course",
        "level_marks",
        ["user_id", "course_id"],
        unique=True,
        schema="lms",
        postgresql_where=sa.text("course_id IS NOT NULL"),
    )
    op.drop_constraint("ck_xp_events_source", "xp_events", schema="lms")
    op.create_check_constraint(
        op.f("ck_xp_events_source"), "xp_events", NEW_SOURCES, schema="lms"
    )


def downgrade() -> None:
    """Drop the level tables and the coach XP source."""
    op.drop_constraint("ck_xp_events_source", "xp_events", schema="lms")
    op.execute("DELETE FROM lms.xp_events WHERE source = 'coach'")
    op.create_check_constraint(
        op.f("ck_xp_events_source"), "xp_events", OLD_SOURCES, schema="lms"
    )
    op.drop_table("level_marks", schema="lms")
    op.drop_table("level_schemes", schema="lms")
