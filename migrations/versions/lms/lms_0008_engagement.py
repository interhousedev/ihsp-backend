"""Engagement: XP ledger, profiles, review queue, mastery settings, class quests.

Revision ID: lms_0008_engagement
Revises: lms_0007_ai_review
Create Date: 2026-11-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "lms_0008_engagement"
down_revision: str | Sequence[str] | None = "lms_0007_ai_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    """Create the engagement tables."""
    op.create_table(
        "xp_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("ref", sa.String(length=128), nullable=False),
        sa.Column("xp", sa.Integer(), nullable=False),
        sa.Column("earned_on", sa.Date(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "source IN ('step', 'test', 'review', 'quest', 'exam', 'widget')",
            name=op.f("ck_xp_events_source"),
        ),
        sa.CheckConstraint("xp >= 0", name=op.f("ck_xp_events_xp_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_xp_events")),
        sa.UniqueConstraint(
            "user_id", "source", "ref", name="uq_xp_events_user_source_ref"
        ),
        schema="lms",
    )
    op.create_index(
        "ix_xp_events_user_id_earned_on",
        "xp_events",
        ["user_id", "earned_on"],
        schema="lms",
    )
    op.create_index(
        "ix_xp_events_course_id_earned_on",
        "xp_events",
        ["course_id", "earned_on"],
        schema="lms",
    )
    op.create_table(
        "engagement_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "weekly_goal_days",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "weekly_goal_days BETWEEN 1 AND 7",
            name=op.f("ck_engagement_profiles_weekly_goal_days"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_engagement_profiles")),
        schema="lms",
    )
    op.create_table(
        "review_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("stability", sa.Float(), nullable=False),
        sa.Column("difficulty", sa.Float(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reps", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lapses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _created_at(),
        _updated_at(),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_review_items_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_items")),
        sa.UniqueConstraint(
            "user_id",
            "step_id",
            "block_id",
            "question_id",
            name="uq_review_items_user_question",
        ),
        schema="lms",
    )
    op.create_index(
        "ix_review_items_user_id_due_at",
        "review_items",
        ["user_id", "due_at"],
        schema="lms",
    )
    op.create_table(
        "course_engagement_settings",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("unlock_threshold_pct", sa.Integer(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "unlock_threshold_pct BETWEEN 1 AND 100",
            name=op.f("ck_course_engagement_settings_unlock_threshold_pct"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_course_engagement_settings_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "course_id", name=op.f("pk_course_engagement_settings")
        ),
        schema="lms",
    )
    op.create_table(
        "class_quests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("goal_kind", sa.String(length=16), nullable=False),
        sa.Column("target", sa.Integer(), nullable=False),
        sa.Column("class_target", sa.Integer(), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "goal_kind IN ('steps', 'xp', 'review_days')",
            name=op.f("ck_class_quests_goal_kind"),
        ),
        sa.CheckConstraint(
            "target > 0 AND class_target > 0",
            name=op.f("ck_class_quests_targets_positive"),
        ),
        sa.CheckConstraint(
            "ends_on >= starts_on", name=op.f("ck_class_quests_dates_ordered")
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_class_quests_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_class_quests")),
        schema="lms",
    )
    op.create_index(
        "ix_class_quests_course_id_ends_on",
        "class_quests",
        ["course_id", "ends_on"],
        schema="lms",
    )


def downgrade() -> None:
    """Drop the engagement tables."""
    op.drop_index(
        "ix_class_quests_course_id_ends_on", table_name="class_quests", schema="lms"
    )
    op.drop_table("class_quests", schema="lms")
    op.drop_table("course_engagement_settings", schema="lms")
    op.drop_index(
        "ix_review_items_user_id_due_at", table_name="review_items", schema="lms"
    )
    op.drop_table("review_items", schema="lms")
    op.drop_table("engagement_profiles", schema="lms")
    op.drop_index(
        "ix_xp_events_course_id_earned_on", table_name="xp_events", schema="lms"
    )
    op.drop_index(
        "ix_xp_events_user_id_earned_on", table_name="xp_events", schema="lms"
    )
    op.drop_table("xp_events", schema="lms")
