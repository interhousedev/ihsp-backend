"""lms init

Revision ID: lms_0001
Revises:
Create Date: 2026-10-07 17:00:54.154280

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "lms_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("lms",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS lms")
    op.create_table(
        "courses",
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "description", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("cover_file_id", sa.Uuid(), nullable=True),
        sa.Column(
            "visibility",
            sa.Enum(
                "public",
                "invite",
                name="visibility",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("invite_code", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "archived",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "draft_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "draft_outline",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{\"sections\": []}'::jsonb"),
            nullable=False,
        ),
        sa.Column("draft_updated_by", sa.Uuid(), nullable=True),
        sa.Column("draft_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "draft_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("outline_hash", sa.String(length=64), nullable=False),
        sa.Column("live_outline_hash", sa.String(length=64), nullable=True),
        sa.Column("live_version_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_courses")),
        sa.UniqueConstraint("slug", name="uq_courses_slug"),
        schema="lms",
    )
    op.create_index(
        "ix_courses_invite_code",
        "courses",
        ["invite_code"],
        unique=True,
        schema="lms",
        postgresql_where=sa.text("invite_code IS NOT NULL"),
    )
    op.create_table(
        "course_staff",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column(
            "permissions",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "show_on_page",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("added_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
            "permissions <@ ARRAY['edit', 'publish', 'review', 'manage_staff', 'view_drafts']::text[]",
            name=op.f("ck_course_staff_permissions"),
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_course_staff_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_course_staff")),
        sa.UniqueConstraint("course_id", "user_id", name="uq_course_staff_course_user"),
        schema="lms",
    )
    op.create_index(
        "ix_course_staff_user_id",
        "course_staff",
        ["user_id"],
        unique=False,
        schema="lms",
    )
    op.create_table(
        "course_steps",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("draft", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("draft_hash", sa.String(length=64), nullable=False),
        sa.Column("draft_updated_by", sa.Uuid(), nullable=True),
        sa.Column("draft_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "draft_updated_via",
            sa.Enum(
                "ui",
                "mcp",
                name="draft_updated_via",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'ui'"),
            nullable=False,
        ),
        sa.Column(
            "file_ids",
            sa.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("live_revision_id", sa.Uuid(), nullable=True),
        sa.Column("live_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_via",
            sa.Enum(
                "ui",
                "mcp",
                name="created_via",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'ui'"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_course_steps_course_id_courses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_course_steps")),
        schema="lms",
    )
    op.create_index(
        "ix_course_steps_course_id",
        "course_steps",
        ["course_id"],
        unique=False,
        schema="lms",
    )
    op.create_index(
        "ix_course_steps_file_ids",
        "course_steps",
        ["file_ids"],
        unique=False,
        schema="lms",
        postgresql_using="gin",
    )
    op.create_table(
        "course_versions",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outline", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_course_versions_course_id_courses"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_course_versions")),
        sa.UniqueConstraint(
            "course_id", "number", name="uq_course_versions_course_number"
        ),
        schema="lms",
    )
    op.create_table(
        "enrollments",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "via",
            sa.Enum(
                "self", "invite", name="via", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "progress_pct",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("progress_version_id", sa.Uuid(), nullable=True),
        sa.Column("last_seen_version_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
            "progress_pct BETWEEN 0 AND 100", name=op.f("ck_enrollments_progress_pct")
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_enrollments_course_id_courses"),
        ),
        sa.ForeignKeyConstraint(
            ["last_seen_version_id"],
            ["lms.course_versions.id"],
            name=op.f("fk_enrollments_last_seen_version_id_course_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["progress_version_id"],
            ["lms.course_versions.id"],
            name=op.f("fk_enrollments_progress_version_id_course_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_enrollments")),
        sa.UniqueConstraint("course_id", "user_id", name="uq_enrollments_course_user"),
        schema="lms",
    )
    op.create_index(
        "ix_enrollments_user_id", "enrollments", ["user_id"], unique=False, schema="lms"
    )
    op.create_table(
        "step_revisions",
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "publish",
                "checkpoint",
                "preview",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "file_ids",
            sa.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
            ["step_id"],
            ["lms.course_steps.id"],
            name=op.f("fk_step_revisions_step_id_course_steps"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_step_revisions")),
        sa.UniqueConstraint(
            "step_id", "content_hash", name="uq_step_revisions_step_content_hash"
        ),
        schema="lms",
    )
    op.create_index(
        "ix_step_revisions_file_ids",
        "step_revisions",
        ["file_ids"],
        unique=False,
        schema="lms",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_step_revisions_step_id_kind_created_at",
        "step_revisions",
        ["step_id", "kind", "created_at"],
        unique=False,
        schema="lms",
    )
    op.create_table(
        "step_states",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cards",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
            ["step_id"],
            ["lms.course_steps.id"],
            name=op.f("fk_step_states_step_id_course_steps"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_step_states")),
        sa.UniqueConstraint("user_id", "step_id", name="uq_step_states_user_step"),
        schema="lms",
    )
    op.create_index(
        "ix_step_states_step_id", "step_states", ["step_id"], unique=False, schema="lms"
    )
    op.create_table(
        "test_attempts",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_no", sa.SmallInteger(), nullable=False),
        sa.Column(
            "is_preview", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("variant", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("score", sa.Numeric(), nullable=True),
        sa.Column("max_score", sa.Numeric(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("override_score", sa.Numeric(), nullable=True),
        sa.Column("override_comment", sa.String(length=1000), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
            ["revision_id"],
            ["lms.step_revisions.id"],
            name=op.f("fk_test_attempts_revision_id_step_revisions"),
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["lms.course_steps.id"],
            name=op.f("fk_test_attempts_step_id_course_steps"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_attempts")),
        schema="lms",
    )
    op.create_index(
        "ix_test_attempts_attempt_no",
        "test_attempts",
        ["user_id", "step_id", "block_id", "attempt_no"],
        unique=True,
        schema="lms",
        postgresql_where=sa.text("NOT is_preview"),
    )
    op.create_index(
        "ix_test_attempts_revision_id",
        "test_attempts",
        ["revision_id"],
        unique=False,
        schema="lms",
    )
    op.create_index(
        "ix_test_attempts_step_id_submitted_at",
        "test_attempts",
        ["step_id", "submitted_at"],
        unique=False,
        schema="lms",
    )
    # Circular references (courses <-> course_versions, course_steps <->
    # step_revisions): added after both tables exist.
    op.create_foreign_key(
        "fk_courses_live_version_id_course_versions",
        "courses",
        "course_versions",
        ["live_version_id"],
        ["id"],
        source_schema="lms",
        referent_schema="lms",
    )
    op.create_foreign_key(
        "fk_course_steps_live_revision_id_step_revisions",
        "course_steps",
        "step_revisions",
        ["live_revision_id"],
        ["id"],
        source_schema="lms",
        referent_schema="lms",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_course_steps_live_revision_id_step_revisions",
        "course_steps",
        schema="lms",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_courses_live_version_id_course_versions",
        "courses",
        schema="lms",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_test_attempts_step_id_submitted_at",
        table_name="test_attempts",
        schema="lms",
    )
    op.drop_index(
        "ix_test_attempts_revision_id", table_name="test_attempts", schema="lms"
    )
    op.drop_index(
        "ix_test_attempts_attempt_no",
        table_name="test_attempts",
        schema="lms",
        postgresql_where=sa.text("NOT is_preview"),
    )
    op.drop_table("test_attempts", schema="lms")
    op.drop_index("ix_step_states_step_id", table_name="step_states", schema="lms")
    op.drop_table("step_states", schema="lms")
    op.drop_index(
        "ix_step_revisions_step_id_kind_created_at",
        table_name="step_revisions",
        schema="lms",
    )
    op.drop_index(
        "ix_step_revisions_file_ids",
        table_name="step_revisions",
        schema="lms",
        postgresql_using="gin",
    )
    op.drop_table("step_revisions", schema="lms")
    op.drop_index("ix_enrollments_user_id", table_name="enrollments", schema="lms")
    op.drop_table("enrollments", schema="lms")
    op.drop_table("course_versions", schema="lms")
    op.drop_index(
        "ix_course_steps_file_ids",
        table_name="course_steps",
        schema="lms",
        postgresql_using="gin",
    )
    op.drop_index("ix_course_steps_course_id", table_name="course_steps", schema="lms")
    op.drop_table("course_steps", schema="lms")
    op.drop_index("ix_course_staff_user_id", table_name="course_staff", schema="lms")
    op.drop_table("course_staff", schema="lms")
    op.drop_index(
        "ix_courses_invite_code",
        table_name="courses",
        schema="lms",
        postgresql_where=sa.text("invite_code IS NOT NULL"),
    )
    op.drop_table("courses", schema="lms")
    op.execute("DROP SCHEMA IF EXISTS lms CASCADE")
