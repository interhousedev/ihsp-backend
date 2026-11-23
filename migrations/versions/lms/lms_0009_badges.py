"""Course badges: designs with a rule, awards, per-course settings.

Revision ID: lms_0009_badges
Revises: lms_0008_engagement
Create Date: 2026-11-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "lms_0009_badges"
down_revision: str | Sequence[str] | None = "lms_0008_engagement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    """Create the badge tables."""
    op.create_table(
        "badges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("name", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "description",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("icon", sa.String(length=16), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("shape", sa.String(length=16), nullable=False),
        sa.Column("image_file_id", sa.Uuid(), nullable=True),
        sa.Column("rule", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "position", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(
            "shape IN ('circle', 'shield', 'hexagon', 'star')",
            name=op.f("ck_badges_shape"),
        ),
        sa.CheckConstraint("color ~ '^#[0-9a-f]{6}$'", name=op.f("ck_badges_color")),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_badges_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_badges")),
        schema="lms",
    )
    op.create_index("ix_badges_course_id", "badges", ["course_id"], schema="lms")
    op.create_table(
        "badge_awards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("badge_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        _ts("awarded_at"),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["badge_id"],
            ["lms.badges.id"],
            name=op.f("fk_badge_awards_badge_id_badges"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_badge_awards_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_badge_awards")),
        sa.UniqueConstraint("badge_id", "user_id", name="uq_badge_awards_badge_user"),
        schema="lms",
    )
    op.create_index(
        "ix_badge_awards_user_id_course_id",
        "badge_awards",
        ["user_id", "course_id"],
        schema="lms",
    )
    op.create_table(
        "badge_settings",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column(
            "show_locked", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_badge_settings_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("course_id", name=op.f("pk_badge_settings")),
        schema="lms",
    )


def downgrade() -> None:
    """Drop the badge tables."""
    op.drop_table("badge_settings", schema="lms")
    op.drop_index(
        "ix_badge_awards_user_id_course_id", table_name="badge_awards", schema="lms"
    )
    op.drop_table("badge_awards", schema="lms")
    op.drop_index("ix_badges_course_id", table_name="badges", schema="lms")
    op.drop_table("badges", schema="lms")
