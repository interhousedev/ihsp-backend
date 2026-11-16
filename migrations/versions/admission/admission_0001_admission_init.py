"""admission init: every table of the admission schema.

Revision ID: admission_0001
Revises:
Create Date: 2026-11-16 15:46:18.814020

Students and staff are identity users (no cross-schema foreign keys). Built-in
staff sub-roles are seeded; `pg_trgm` backs the institution name search.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from uuid_utils.compat import uuid7

# revision identifiers, used by Alembic.
revision: str = "admission_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("admission",)
depends_on: str | Sequence[str] | None = None

_BUILTIN_ROLES = (
    ('counselor_full', 'counselor', ('Maslahatchi (toʼliq)', 'Консультант (полный доступ)', 'Counselor (full)'), ('activities:comment', 'activities:read', 'affordability:sign_off', 'catalog:curate', 'confidential:read', 'deadlines:manage', 'documents:attach', 'documents:read', 'documents:review', 'essays:comment', 'essays:read', 'estimates:view_uncalibrated', 'finance:read', 'labels:override', 'list:comment', 'list:read', 'notes:staff', 'profile:comment', 'profile:read', 'students:assign', 'transcripts:oversee', 'words:comment', 'words:read')),
    ('counselor_documents', 'counselor', ('Maslahatchi (hujjatlar)', 'Консультант (документы)', 'Counselor (documents)'), ('deadlines:manage', 'documents:attach', 'documents:read', 'documents:review', 'list:read', 'profile:read', 'transcripts:oversee')),
    ('student_counselor', 'mentor', ('Talaba-maslahatchi', 'Студент-консультант', 'Student counselor'), ('activities:comment', 'activities:read', 'essays:comment', 'essays:read', 'list:comment', 'list:read', 'profile:comment', 'profile:read', 'words:comment', 'words:read')),
    ('essay_mentor', 'mentor', ('Insho boʼyicha mentor', 'Ментор по эссе', 'Essay mentor'), ('essays:comment', 'essays:read', 'words:read')),
    ('transcript_officer', 'transcript_officer', ('Transkript masʼuli', 'Ответственный за транскрипты', 'Transcript officer'), ('transcripts:fulfil',)),
)  # fmt: skip


def upgrade() -> None:
    """Create the schema, the tables and the built-in sub-roles."""
    op.execute("CREATE SCHEMA IF NOT EXISTS admission")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "audit_events",
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_kind", sa.String(length=8), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=True),
        sa.Column("object_type", sa.String(length=40), nullable=True),
        sa.Column("object_id", sa.Uuid(), nullable=True),
        sa.Column("staff_role_id", sa.Uuid(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'guest', 'system')",
            name=op.f("ck_audit_events_actor_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        schema="admission",
    )
    op.create_index(
        "ix_audit_events_student_id_at",
        "audit_events",
        ["student_id", "at"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "comments",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("target_kind", sa.String(length=12), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("anchor", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "target_kind IN ('profile', 'item', 'list_entry', 'essay', 'words', 'help_request')",
            name=op.f("ck_comments_target_kind"),
        ),
        sa.CheckConstraint(
            "visibility IN ('student_and_staff', 'staff_only')",
            name=op.f("ck_comments_visibility"),
        ),
        sa.CheckConstraint(
            "char_length(body) <= 2000", name=op.f("ck_comments_body_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_comments_student_id"),
        "comments",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_index(
        "ix_comments_target",
        "comments",
        ["target_kind", "target_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "courses",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=True),
        sa.Column("level", sa.String(length=40), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("grade", sa.String(length=20), nullable=True),
        sa.Column(
            "included", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source = 'manual' OR source_ref IS NOT NULL",
            name=op.f("ck_courses_source_ref"),
        ),
        sa.CheckConstraint(
            "source IN ('academic', 'lms', 'manual')", name=op.f("ck_courses_source")
        ),
        sa.CheckConstraint(
            "char_length(title) <= 200", name=op.f("ck_courses_title_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_courses")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_courses_student_id"),
        "courses",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_index(
        "uq_courses_source_ref",
        "courses",
        ["student_id", "source", "source_ref"],
        unique=True,
        schema="admission",
        postgresql_where=sa.text("source_ref IS NOT NULL"),
    )
    op.create_table(
        "documents",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=14), nullable=False),
        sa.Column(
            "current_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "visibility", sa.String(length=12), server_default="student", nullable=False
        ),
        sa.Column(
            "owner_kind", sa.String(length=12), server_default="student", nullable=False
        ),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column(
            "review_status", sa.String(length=10), server_default="none", nullable=False
        ),
        sa.Column("reject_reason_code", sa.String(length=40), nullable=True),
        sa.Column("reject_note", sa.Text(), nullable=True),
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
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('transcript', 'school_report', 'rec', 'certificate', 'passport', 'translation', 'test_report', 'bank', 'other')",
            name=op.f("ck_documents_kind"),
        ),
        sa.CheckConstraint(
            "owner_kind IN ('student', 'institution')",
            name=op.f("ck_documents_owner_kind"),
        ),
        sa.CheckConstraint(
            "review_status IN ('none', 'accepted', 'rejected')",
            name=op.f("ck_documents_review_status"),
        ),
        sa.CheckConstraint(
            "visibility IN ('student', 'confidential')",
            name=op.f("ck_documents_visibility"),
        ),
        sa.CheckConstraint(
            "char_length(reject_note) <= 300",
            name=op.f("ck_documents_reject_note_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_documents_student_id"),
        "documents",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "entitlements",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("cohort_year", sa.Integer(), nullable=True),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('school_student', 'alumni', 'staff')",
            name=op.f("ck_entitlements_kind"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_entitlements")),
        schema="admission",
    )
    op.create_table(
        "institutions",
        sa.Column("slug", sa.String(length=80), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_local", sa.String(length=200), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("website_domain", sa.String(length=200), nullable=True),
        sa.Column("ror_id", sa.String(length=40), nullable=True),
        sa.Column(
            "kind", sa.String(length=20), server_default="university", nullable=False
        ),
        sa.Column("size_band", sa.String(length=10), nullable=True),
        sa.Column("setting", sa.String(length=14), nullable=True),
        sa.Column(
            "languages",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=12), server_default="provisional", nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('university', 'college', 'foundation_provider')",
            name=op.f("ck_institutions_kind"),
        ),
        sa.CheckConstraint(
            "setting IS NULL OR setting IN ('big_city', 'college_town', 'campus', 'small_city')",
            name=op.f("ck_institutions_setting"),
        ),
        sa.CheckConstraint(
            "status IN ('published', 'provisional', 'archived')",
            name=op.f("ck_institutions_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_institutions")),
        sa.UniqueConstraint("slug", name=op.f("uq_institutions_slug")),
        schema="admission",
    )
    op.create_index(
        "ix_institutions_country",
        "institutions",
        ["country"],
        unique=False,
        schema="admission",
    )
    op.create_index(
        "ix_institutions_name_trgm",
        "institutions",
        ["name"],
        unique=False,
        schema="admission",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_table(
        "items",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("position", sa.String(length=50), nullable=False),
        sa.Column("org", sa.String(length=100), server_default="", nullable=False),
        sa.Column(
            "description", sa.String(length=150), server_default="", nullable=False
        ),
        sa.Column("category", sa.String(length=40), nullable=True),
        sa.Column(
            "grade_levels",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("hours_week", sa.Integer(), nullable=True),
        sa.Column("weeks_year", sa.Integer(), nullable=True),
        sa.Column("started_on", sa.Date(), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column(
            "sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False
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
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "char_length(description) <= CASE WHEN kind = 'honor' THEN 100 ELSE 150 END",
            name=op.f("ck_items_description_length"),
        ),
        sa.CheckConstraint("kind IN ('activity', 'honor')", name=op.f("ck_items_kind")),
        sa.CheckConstraint("char_length(org) <= 100", name=op.f("ck_items_org_length")),
        sa.CheckConstraint(
            "char_length(position) <= 50", name=op.f("ck_items_position_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
        schema="admission",
    )
    op.create_index(
        "ix_items_student_id_sort_order",
        "items",
        ["student_id", "sort_order"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "officer_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "pickup_location",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_officer_settings")),
        schema="admission",
    )
    op.create_table(
        "places",
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "level IN ('country', 'city')", name=op.f("ck_places_level")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_places")),
        schema="admission",
    )
    op.create_table(
        "preferences",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("student_id", "version", name=op.f("pk_preferences")),
        schema="admission",
    )
    op.create_table(
        "profile_words",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column(
            "words",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "candidates",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "source", sa.String(length=8), server_default="manual", nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "source IN ('ai', 'manual', 'mixed')", name=op.f("ck_profile_words_source")
        ),
        sa.CheckConstraint(
            "cardinality(words) <= 3", name=op.f("ck_profile_words_words_count")
        ),
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_profile_words")),
        schema="admission",
    )
    op.create_table(
        "profile_words_history",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("words", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "student_id", "version", name=op.f("pk_profile_words_history")
        ),
        schema="admission",
    )
    op.create_table(
        "profiles",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column(
            "account_kind",
            sa.String(length=8),
            server_default="student",
            nullable=False,
        ),
        sa.Column("cycle", sa.Integer(), nullable=True),
        sa.Column(
            "stage", sa.String(length=12), server_default="setup", nullable=False
        ),
        sa.Column("question_set_version", sa.String(length=40), nullable=False),
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "intended_majors",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "minors",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("career_plan", sa.Text(), nullable=True),
        sa.Column("budget_band", sa.String(length=16), nullable=True),
        sa.Column("aid_need", sa.String(length=8), nullable=True),
        sa.Column("fee_waiver_need", sa.Boolean(), nullable=True),
        sa.Column(
            "finance_visible_to_counselor",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "academics_source",
            sa.String(length=16),
            server_default="emis",
            nullable=False,
        ),
        sa.Column(
            "mentee_opt_in",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "mentor_opt_in",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "helper_opt_in",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("helper_display_name", sa.String(length=60), nullable=True),
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "academics_source IN ('emis', 'self_reported')",
            name=op.f("ck_profiles_academics_source"),
        ),
        sa.CheckConstraint(
            "account_kind IN ('student', 'alumni')",
            name=op.f("ck_profiles_account_kind"),
        ),
        sa.CheckConstraint(
            "aid_need IS NULL OR aid_need IN ('none', 'partial', 'full')",
            name=op.f("ck_profiles_aid_need"),
        ),
        sa.CheckConstraint(
            "stage IN ('setup', 'words', 'items', 'chooser', 'docs', 'submitted')",
            name=op.f("ck_profiles_stage"),
        ),
        sa.CheckConstraint(
            "char_length(helper_display_name) <= 60",
            name=op.f("ck_profiles_helper_display_name_length"),
        ),
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_profiles")),
        schema="admission",
    )
    op.create_table(
        "reminder_prefs",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column(
            "offsets_days",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{60,30,14,7,3,1}'"),
            nullable=False,
        ),
        sa.Column(
            "channels",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{telegram,push,email}'"),
            nullable=False,
        ),
        sa.Column(
            "quiet_from", sa.Time(), server_default=sa.text("'22:00'"), nullable=False
        ),
        sa.Column(
            "quiet_to", sa.Time(), server_default=sa.text("'08:00'"), nullable=False
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "channels <@ ARRAY['telegram', 'push', 'email']::text[]",
            name=op.f("ck_reminder_prefs_channels"),
        ),
        sa.CheckConstraint(
            "offsets_days <@ ARRAY[60, 30, 14, 7, 3, 1]",
            name=op.f("ck_reminder_prefs_offsets_days"),
        ),
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_reminder_prefs")),
        schema="admission",
    )
    op.create_table(
        "reviews",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("target_kind", sa.String(length=10), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("rubric_version", sa.String(length=40), nullable=True),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("words_version", sa.Integer(), nullable=True),
        sa.Column(
            "grades",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("overall", sa.String(length=1), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "safety_flag", sa.String(length=20), server_default="none", nullable=False
        ),
        sa.Column(
            "status", sa.String(length=10), server_default="in_flight", nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "safety_flag IN ('none', 'injection_suspected', 'safeguarding')",
            name=op.f("ck_reviews_safety_flag"),
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'in_flight', 'failed')", name=op.f("ck_reviews_status")
        ),
        sa.CheckConstraint(
            "target_kind IN ('item', 'essay', 'alignment')",
            name=op.f("ck_reviews_target_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
        sa.UniqueConstraint(
            "target_kind", "target_id", "input_hash", name="uq_reviews_input"
        ),
        schema="admission",
    )
    op.create_index(
        "ix_reviews_student_id",
        "reviews",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "routes",
        sa.Column("system", sa.String(length=20), nullable=False),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routes")),
        schema="admission",
    )
    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_runtime_settings")),
        schema="admission",
    )
    op.create_table(
        "sources",
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("licence", sa.String(length=80), nullable=True),
        sa.Column(
            "redistributable",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("refresh_sla_days", sa.Integer(), nullable=True),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_file_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('official_page', 'structured_api', 'dataset', 'manual')",
            name=op.f("ck_sources_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        schema="admission",
    )
    op.create_table(
        "staff_roles",
        sa.Column("key", sa.String(length=40), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column(
            "name_i18n",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "is_builtin", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('counselor', 'mentor', 'transcript_officer')",
            name=op.f("ck_staff_roles_kind"),
        ),
        sa.CheckConstraint(
            "char_length(name) <= 60", name=op.f("ck_staff_roles_name_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_roles")),
        sa.UniqueConstraint("key", name=op.f("uq_staff_roles_key")),
        schema="admission",
    )
    op.create_table(
        "staff_saved_views",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("scope_kind", sa.String(length=8), nullable=False),
        sa.Column("scope_ref", sa.Uuid(), nullable=True),
        sa.Column(
            "filters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("sort", sa.String(length=40), nullable=True),
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "scope_kind IN ('all', 'cohort', 'student')",
            name=op.f("ck_staff_saved_views_scope_kind"),
        ),
        sa.CheckConstraint(
            "char_length(name) <= 60", name=op.f("ck_staff_saved_views_name_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_saved_views")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_staff_saved_views_user_id"),
        "staff_saved_views",
        ["user_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "admission_stats",
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("cohort", sa.String(length=14), nullable=False),
        sa.Column("applicants", sa.Integer(), nullable=True),
        sa.Column("admits", sa.Integer(), nullable=True),
        sa.Column("enrolled", sa.Integer(), nullable=True),
        sa.Column("acceptance_rate", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "tests",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "gpa_bands",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("test_submit_share", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "cohort IN ('all', 'international', 'first_year')",
            name=op.f("ck_admission_stats_cohort"),
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_admission_stats_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["admission.sources.id"],
            name=op.f("fk_admission_stats_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_stats")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_admission_stats_institution_id"),
        "admission_stats",
        ["institution_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "aid_policies",
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column(
            "intl_need_based",
            sa.String(length=10),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("meets_full_need", sa.Boolean(), nullable=True),
        sa.Column(
            "merit_available",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("avg_intl_award", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "forms",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "intl_need_based IN ('need_blind', 'need_aware', 'none', 'unknown')",
            name=op.f("ck_aid_policies_intl_need_based"),
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_aid_policies_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["admission.sources.id"],
            name=op.f("fk_aid_policies_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_aid_policies")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_aid_policies_institution_id"),
        "aid_policies",
        ["institution_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "campuses",
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column(
            "is_branch", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_campuses_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campuses")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_campuses_institution_id"),
        "campuses",
        ["institution_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "costs_of_attendance",
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("tuition", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("housing", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("other", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_costs_of_attendance_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["admission.sources.id"],
            name=op.f("fk_costs_of_attendance_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_costs_of_attendance")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_costs_of_attendance_institution_id"),
        "costs_of_attendance",
        ["institution_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "deck_decisions",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("reason_chip", sa.String(length=40), nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('shortlist', 'hide')", name=op.f("ck_deck_decisions_decision")
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_deck_decisions_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deck_decisions")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_deck_decisions_student_id"),
        "deck_decisions",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "document_versions",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scan_status",
            sa.String(length=12),
            server_default="pending_scan",
            nullable=False,
        ),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "scan_status IN ('pending_scan', 'clean', 'infected', 'failed', 'unscanned')",
            name=op.f("ck_document_versions_scan_status"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["admission.documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        schema="admission",
    )
    op.create_index(
        "uq_document_versions_doc_version",
        "document_versions",
        ["document_id", "version"],
        unique=True,
        schema="admission",
    )
    op.create_table(
        "eligibility_rules",
        sa.Column("system", sa.String(length=20), nullable=False),
        sa.Column("qualification", sa.String(length=30), nullable=False),
        sa.Column("outcome", sa.String(length=14), nullable=False),
        sa.Column(
            "conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('direct', 'foundation', 'studienkolleg', 'unknown')",
            name=op.f("ck_eligibility_rules_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["admission.sources.id"],
            name=op.f("fk_eligibility_rules_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eligibility_rules")),
        schema="admission",
    )
    op.create_table(
        "facts",
        sa.Column("entity_kind", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("cycle", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("excerpt", sa.String(length=300), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column(
            "consequential",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=10), server_default="proposed", nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "confidence IN ('manual', 'official', 'structured_api', 'ai_extracted')",
            name=op.f("ck_facts_confidence"),
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'published', 'rejected', 'stale')",
            name=op.f("ck_facts_status"),
        ),
        sa.CheckConstraint(
            "char_length(excerpt) <= 300", name=op.f("ck_facts_excerpt_length")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["admission.sources.id"],
            name=op.f("fk_facts_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_facts")),
        schema="admission",
    )
    op.create_index(
        "ix_facts_entity",
        "facts",
        ["entity_kind", "entity_id", "key"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "help_requests",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default="open", nullable=False
        ),
        sa.Column("helper_user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('website', 'design', 'proof', 'other')",
            name=op.f("ck_help_requests_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'assigned', 'accepted', 'declined', 'delivered', 'closed', 'cancelled', 'expired')",
            name=op.f("ck_help_requests_status"),
        ),
        sa.CheckConstraint(
            "char_length(brief) <= 1000", name=op.f("ck_help_requests_brief_length")
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["admission.items.id"],
            name=op.f("fk_help_requests_item_id_items"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_help_requests")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_help_requests_helper_user_id"),
        "help_requests",
        ["helper_user_id"],
        unique=False,
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_help_requests_student_id"),
        "help_requests",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "item_interviews",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "round BETWEEN 1 AND 3", name=op.f("ck_item_interviews_round")
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["admission.items.id"],
            name=op.f("fk_item_interviews_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_item_interviews")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_item_interviews_item_id"),
        "item_interviews",
        ["item_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "item_metrics",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("unit", sa.String(length=24), nullable=True),
        sa.Column("horizon", sa.String(length=10), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column(
            "provenance",
            sa.String(length=24),
            server_default="self_stated",
            nullable=False,
        ),
        sa.Column("evidence_claim_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "horizon <> 'projected' OR target_date IS NOT NULL",
            name=op.f("ck_item_metrics_projected_date"),
        ),
        sa.CheckConstraint(
            "horizon IN ('current', 'projected')", name=op.f("ck_item_metrics_horizon")
        ),
        sa.CheckConstraint(
            "provenance IN ('self_stated', 'source_supported', 'independently_verified')",
            name=op.f("ck_item_metrics_provenance"),
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["admission.items.id"],
            name=op.f("fk_item_metrics_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_item_metrics")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_item_metrics_item_id"),
        "item_metrics",
        ["item_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "proofs",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("text_sha256", sa.String(length=64), nullable=True),
        sa.Column("extraction", sa.String(length=10), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(length=14), server_default="pending", nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "extraction IS NULL OR extraction IN ('html', 'pdf_text', 'ocr', 'pasted')",
            name=op.f("ck_proofs_extraction"),
        ),
        sa.CheckConstraint(
            "kind IN ('linkedin', 'telegram', 'website', 'file', 'self_provided')",
            name=op.f("ck_proofs_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'checked', 'unverifiable', 'failed')",
            name=op.f("ck_proofs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["admission.items.id"],
            name=op.f("fk_proofs_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proofs")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_proofs_item_id"),
        "proofs",
        ["item_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "review_feedback",
        sa.Column("review_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('unfair', 'helpful')", name=op.f("ck_review_feedback_kind")
        ),
        sa.CheckConstraint(
            "char_length(note) <= 500", name=op.f("ck_review_feedback_note_length")
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["admission.reviews.id"],
            name=op.f("fk_review_feedback_review_id_reviews"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_feedback")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_review_feedback_review_id"),
        "review_feedback",
        ["review_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "scholarships",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=12), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("basis", sa.String(length=12), nullable=False),
        sa.Column("coverage_pct_min", sa.Integer(), nullable=True),
        sa.Column("coverage_pct_max", sa.Integer(), nullable=True),
        sa.Column(
            "covers",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "eligibility",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("deadline_id", sa.Uuid(), nullable=True),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status", sa.String(length=12), server_default="provisional", nullable=False
        ),
        sa.Column("cycle", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "basis IN ('merit', 'need', 'government', 'sports', 'work_study')",
            name=op.f("ck_scholarships_basis"),
        ),
        sa.CheckConstraint(
            "provider IN ('institution', 'government', 'foundation')",
            name=op.f("ck_scholarships_provider"),
        ),
        sa.CheckConstraint(
            "status IN ('published', 'provisional')",
            name=op.f("ck_scholarships_status"),
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_scholarships_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["admission.sources.id"],
            name=op.f("fk_scholarships_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scholarships")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_scholarships_institution_id"),
        "scholarships",
        ["institution_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "staff_assignments",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("staff_role_id", sa.Uuid(), nullable=False),
        sa.Column("scope_kind", sa.String(length=8), nullable=False),
        sa.Column("scope_ref", sa.Uuid(), nullable=True),
        sa.Column(
            "starts_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("granted_via", sa.String(length=12), nullable=False),
        sa.Column("parent_assignment_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=40), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "granted_via IN ('admin', 'delegation')",
            name=op.f("ck_staff_assignments_granted_via"),
        ),
        sa.CheckConstraint(
            "scope_kind IN ('all', 'cohort', 'student')",
            name=op.f("ck_staff_assignments_scope_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_assignment_id"],
            ["admission.staff_assignments.id"],
            name=op.f("fk_staff_assignments_parent_assignment_id_staff_assignments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["staff_role_id"],
            ["admission.staff_roles.id"],
            name=op.f("fk_staff_assignments_staff_role_id_staff_roles"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_assignments")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_staff_assignments_parent_assignment_id"),
        "staff_assignments",
        ["parent_assignment_id"],
        unique=False,
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_staff_assignments_user_id"),
        "staff_assignments",
        ["user_id"],
        unique=False,
        schema="admission",
    )
    op.create_index(
        "ix_staff_assignments_scope",
        "staff_assignments",
        ["scope_kind", "scope_ref"],
        unique=False,
        schema="admission",
    )
    op.create_index(
        "uq_staff_assignments_live",
        "staff_assignments",
        ["user_id", "staff_role_id", "scope_kind", "scope_ref"],
        unique=True,
        schema="admission",
        postgresql_where=sa.text("revoked_at IS NULL"),
        postgresql_nulls_not_distinct=True,
    )
    op.create_table(
        "transcript_requests",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("destination_note", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=10), server_default="requested", nullable=False
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ready_by", sa.Uuid(), nullable=True),
        sa.Column("undo_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pickup_location_snapshot", sa.Text(), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'ready', 'cancelled')",
            name=op.f("ck_transcript_requests_status"),
        ),
        sa.CheckConstraint(
            "char_length(destination_note) <= 200",
            name=op.f("ck_transcript_requests_destination_note_length"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["admission.documents.id"],
            name=op.f("fk_transcript_requests_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transcript_requests")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_transcript_requests_student_id"),
        "transcript_requests",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_index(
        "uq_transcript_requests_open",
        "transcript_requests",
        ["student_id"],
        unique=True,
        schema="admission",
        postgresql_where=sa.text("status = 'requested'"),
    )
    op.create_table(
        "goal_milestones",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column("metric_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("due_month", sa.Date(), nullable=True),
        sa.Column("target_value", sa.Numeric(), nullable=True),
        sa.Column(
            "status", sa.String(length=8), server_default="planned", nullable=False
        ),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source", sa.String(length=8), server_default="manual", nullable=False
        ),
        sa.Column(
            "sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "source IN ('ai', 'manual')", name=op.f("ck_goal_milestones_source")
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'done', 'dropped')",
            name=op.f("ck_goal_milestones_status"),
        ),
        sa.CheckConstraint(
            "char_length(title) <= 120", name=op.f("ck_goal_milestones_title_length")
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["admission.items.id"],
            name=op.f("fk_goal_milestones_item_id_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["metric_id"],
            ["admission.item_metrics.id"],
            name=op.f("fk_goal_milestones_metric_id_item_metrics"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goal_milestones")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_goal_milestones_student_id"),
        "goal_milestones",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "guest_links",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("help_request_id", sa.Uuid(), nullable=False),
        sa.Column("scope", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=8), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "max_sessions", sa.Integer(), server_default=sa.text("5"), nullable=False
        ),
        sa.Column(
            "sessions_used", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=40), nullable=True),
        sa.Column("rotated_from", sa.Uuid(), nullable=True),
        sa.Column("claimed_by", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '60 days'",
            name=op.f("ck_guest_links_expires_at"),
        ),
        sa.CheckConstraint(
            "scope <@ ARRAY['activities:read', 'help:respond']::text[]",
            name=op.f("ck_guest_links_scope"),
        ),
        sa.CheckConstraint(
            "max_sessions BETWEEN 1 AND 20", name=op.f("ck_guest_links_max_sessions")
        ),
        sa.ForeignKeyConstraint(
            ["help_request_id"],
            ["admission.help_requests.id"],
            name=op.f("fk_guest_links_help_request_id_help_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guest_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_guest_links_token_hash")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_guest_links_student_id"),
        "guest_links",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "programs",
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("campus_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("cip_code", sa.String(length=10), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("duration_years", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "level IN ('bachelor', 'foundation', '2plus2')",
            name=op.f("ck_programs_level"),
        ),
        sa.ForeignKeyConstraint(
            ["campus_id"],
            ["admission.campuses.id"],
            name=op.f("fk_programs_campus_id_campuses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_programs_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_programs")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_programs_institution_id"),
        "programs",
        ["institution_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "proof_claims",
        sa.Column("proof_id", sa.Uuid(), nullable=False),
        sa.Column("metric_id", sa.Uuid(), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=18), nullable=False),
        sa.Column(
            "matched",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("quote", sa.String(length=300), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('source_supported', 'partial', 'not_found', 'contradicted', 'unverifiable')",
            name=op.f("ck_proof_claims_status"),
        ),
        sa.CheckConstraint(
            "char_length(quote) <= 300", name=op.f("ck_proof_claims_quote_length")
        ),
        sa.ForeignKeyConstraint(
            ["metric_id"],
            ["admission.item_metrics.id"],
            name=op.f("fk_proof_claims_metric_id_item_metrics"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["proof_id"],
            ["admission.proofs.id"],
            name=op.f("fk_proof_claims_proof_id_proofs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proof_claims")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_proof_claims_proof_id"),
        "proof_claims",
        ["proof_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "safety_facts",
        sa.Column("place_id", sa.Uuid(), nullable=True),
        sa.Column("campus_id", sa.Uuid(), nullable=True),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("indicator", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("band", sa.String(length=16), nullable=True),
        sa.Column("band_version", sa.String(length=20), nullable=True),
        sa.Column("uncertainty", sa.String(length=20), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status", sa.String(length=10), server_default="proposed", nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "indicator IN ('travel_advisory', 'gpi', 'crime_rate', 'clery')",
            name=op.f("ck_safety_facts_indicator"),
        ),
        sa.CheckConstraint(
            "level IN ('country', 'city', 'campus')", name=op.f("ck_safety_facts_level")
        ),
        sa.CheckConstraint(
            "(place_id IS NULL) <> (campus_id IS NULL)",
            name=op.f("ck_safety_facts_place_or_campus"),
        ),
        sa.ForeignKeyConstraint(
            ["campus_id"],
            ["admission.campuses.id"],
            name=op.f("fk_safety_facts_campus_id_campuses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["place_id"],
            ["admission.places.id"],
            name=op.f("fk_safety_facts_place_id_places"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["admission.sources.id"],
            name=op.f("fk_safety_facts_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_safety_facts")),
        schema="admission",
    )
    op.create_table(
        "deadlines",
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=True),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("round", sa.String(length=8), nullable=False),
        sa.Column(
            "precision",
            sa.String(length=10),
            server_default="date_only",
            nullable=False,
        ),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("source_tz", sa.String(length=40), nullable=True),
        sa.Column("local_date", sa.Date(), nullable=True),
        sa.Column("cutoff_time", sa.Time(), nullable=True),
        sa.Column("instant_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "binding", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("applies_to", sa.String(length=40), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default="unknown", nullable=False
        ),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("superseded_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "precision IN ('date_only', 'instant')", name=op.f("ck_deadlines_precision")
        ),
        sa.CheckConstraint(
            "status IN ('confirmed', 'predicted', 'unknown', 'confirm_with_uni')",
            name=op.f("ck_deadlines_status"),
        ),
        sa.CheckConstraint(
            "char_length(source_text) <= 200",
            name=op.f("ck_deadlines_source_text_length"),
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_deadlines_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["admission.programs.id"],
            name=op.f("fk_deadlines_program_id_programs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["admission.sources.id"],
            name=op.f("fk_deadlines_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deadlines")),
        schema="admission",
    )
    op.create_index(
        "ix_deadlines_institution_cycle",
        "deadlines",
        ["institution_id", "cycle"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "guest_sessions",
        sa.Column("guest_link_id", sa.Uuid(), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["guest_link_id"],
            ["admission.guest_links.id"],
            name=op.f("fk_guest_sessions_guest_link_id_guest_links"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guest_sessions")),
        sa.UniqueConstraint(
            "session_hash", name=op.f("uq_guest_sessions_session_hash")
        ),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_guest_sessions_guest_link_id"),
        "guest_sessions",
        ["guest_link_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "help_responses",
        sa.Column("help_request_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("guest_link_id", sa.Uuid(), nullable=True),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(text) <= 2000", name=op.f("ck_help_responses_text_length")
        ),
        sa.ForeignKeyConstraint(
            ["guest_link_id"],
            ["admission.guest_links.id"],
            name=op.f("fk_help_responses_guest_link_id_guest_links"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["help_request_id"],
            ["admission.help_requests.id"],
            name=op.f("fk_help_responses_help_request_id_help_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_help_responses")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_help_responses_help_request_id"),
        "help_responses",
        ["help_request_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "list_entries",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("campus_id", sa.Uuid(), nullable=True),
        sa.Column("program_id", sa.Uuid(), nullable=True),
        sa.Column("round", sa.String(length=8), server_default="RD", nullable=False),
        sa.Column(
            "status", sa.String(length=12), server_default="considering", nullable=False
        ),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aid_offer", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("estimate", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("label_override", sa.String(length=8), nullable=True),
        sa.Column("override_note", sa.Text(), nullable=True),
        sa.Column("override_by", sa.Uuid(), nullable=True),
        sa.Column("override_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "affordability_status",
            sa.String(length=10),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("eligibility_outcome", sa.String(length=14), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "affordability_status IN ('feasible', 'gap', 'unknown', 'signed_off')",
            name=op.f("ck_list_entries_affordability_status"),
        ),
        sa.CheckConstraint(
            "label_override IS NULL OR label_override IN ('reach', 'target', 'safety')",
            name=op.f("ck_list_entries_label_override"),
        ),
        sa.CheckConstraint(
            "round IN ('RD', 'EA', 'ED', 'ED2', 'REA', 'rolling', 'other')",
            name=op.f("ck_list_entries_round"),
        ),
        sa.CheckConstraint(
            "status IN ('considering', 'applying', 'submitted', 'admitted', 'waitlisted', 'deferred', 'rejected', 'enrolled', 'withdrawn')",
            name=op.f("ck_list_entries_status"),
        ),
        sa.CheckConstraint(
            "char_length(override_note) <= 300",
            name=op.f("ck_list_entries_override_note_length"),
        ),
        sa.ForeignKeyConstraint(
            ["campus_id"],
            ["admission.campuses.id"],
            name=op.f("fk_list_entries_campus_id_campuses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_list_entries_institution_id_institutions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["admission.programs.id"],
            name=op.f("fk_list_entries_program_id_programs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_list_entries")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_list_entries_student_id"),
        "list_entries",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "requirements",
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=True),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column(
            "rule",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "international_policy",
            sa.String(length=14),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "international_policy IN ('required', 'optional', 'not_considered', 'unknown')",
            name=op.f("ck_requirements_international_policy"),
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_requirements_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["admission.programs.id"],
            name=op.f("fk_requirements_program_id_programs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["admission.sources.id"],
            name=op.f("fk_requirements_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requirements")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_requirements_institution_id"),
        "requirements",
        ["institution_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "affordability_checks",
        sa.Column("list_entry_id", sa.Uuid(), nullable=False),
        sa.Column("coa_total", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("confirmed_aid", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("estimated_aid", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("family_band", sa.String(length=16), nullable=True),
        sa.Column(
            "enrolment_deposit", sa.Numeric(precision=12, scale=2), nullable=True
        ),
        sa.Column("fees_total", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("gap", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "status", sa.String(length=10), server_default="unknown", nullable=False
        ),
        sa.Column("requested_sign_off_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_off_by", sa.Uuid(), nullable=True),
        sa.Column("signed_off_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sign_off_note", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('feasible', 'gap', 'unknown')",
            name=op.f("ck_affordability_checks_status"),
        ),
        sa.CheckConstraint(
            "char_length(sign_off_note) <= 300",
            name=op.f("ck_affordability_checks_sign_off_note_length"),
        ),
        sa.ForeignKeyConstraint(
            ["list_entry_id"],
            ["admission.list_entries.id"],
            name=op.f("fk_affordability_checks_list_entry_id_list_entries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_affordability_checks")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_affordability_checks_list_entry_id"),
        "affordability_checks",
        ["list_entry_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "checklist_items",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("list_entry_id", sa.Uuid(), nullable=True),
        sa.Column("template_key", sa.String(length=60), nullable=False),
        sa.Column("title_key", sa.String(length=80), nullable=False),
        sa.Column(
            "owner", sa.String(length=10), server_default="student", nullable=False
        ),
        sa.Column(
            "status", sa.String(length=16), server_default="todo", nullable=False
        ),
        sa.Column("due_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column(
            "rule_version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "owner IN ('student', 'counselor', 'officer', 'teacher')",
            name=op.f("ck_checklist_items_owner"),
        ),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'done', 'n_a', 'confirm_with_uni')",
            name=op.f("ck_checklist_items_status"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["admission.documents.id"],
            name=op.f("fk_checklist_items_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["list_entry_id"],
            ["admission.list_entries.id"],
            name=op.f("fk_checklist_items_list_entry_id_list_entries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checklist_items")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_checklist_items_student_id"),
        "checklist_items",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "document_attachments",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("list_entry_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default="attached", nullable=False
        ),
        sa.Column("attached_by", sa.Uuid(), nullable=False),
        sa.Column(
            "attached_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('attached', 'superseded', 'detached')",
            name=op.f("ck_document_attachments_status"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["admission.documents.id"],
            name=op.f("fk_document_attachments_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["list_entry_id"],
            ["admission.list_entries.id"],
            name=op.f("fk_document_attachments_list_entry_id_list_entries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_attachments")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_document_attachments_list_entry_id"),
        "document_attachments",
        ["list_entry_id"],
        unique=False,
        schema="admission",
    )
    op.create_index(
        "uq_document_attachments_live",
        "document_attachments",
        ["document_id", "list_entry_id"],
        unique=True,
        schema="admission",
        postgresql_where=sa.text("status = 'attached'"),
    )
    op.create_table(
        "essays",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("list_entry_id", sa.Uuid(), nullable=True),
        sa.Column("prompt_text", sa.Text(), server_default="", nullable=False),
        sa.Column("word_limit", sa.Integer(), nullable=True),
        sa.Column(
            "current_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "status", sa.String(length=8), server_default="draft", nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'final')", name=op.f("ck_essays_status")
        ),
        sa.ForeignKeyConstraint(
            ["list_entry_id"],
            ["admission.list_entries.id"],
            name=op.f("fk_essays_list_entry_id_list_entries"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_essays")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_essays_student_id"),
        "essays",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "milestones",
        sa.Column("list_entry_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("due_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_id", sa.Uuid(), nullable=True),
        sa.Column("deadline_version", sa.Integer(), nullable=True),
        sa.Column(
            "predicted", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('application', 'aid', 'test_send', 'rec', 'docs', 'decision', 'deposit', 'fee')",
            name=op.f("ck_milestones_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["deadline_id"],
            ["admission.deadlines.id"],
            name=op.f("fk_milestones_deadline_id_deadlines"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["list_entry_id"],
            ["admission.list_entries.id"],
            name=op.f("fk_milestones_list_entry_id_list_entries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_milestones")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_milestones_list_entry_id"),
        "milestones",
        ["list_entry_id"],
        unique=False,
        schema="admission",
    )
    op.create_table(
        "essay_versions",
        sa.Column("essay_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(name) <= 60", name=op.f("ck_essay_versions_name_length")
        ),
        sa.ForeignKeyConstraint(
            ["essay_id"],
            ["admission.essays.id"],
            name=op.f("fk_essay_versions_essay_id_essays"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_essay_versions")),
        sa.UniqueConstraint("essay_id", "version", name="uq_essay_versions_version"),
        schema="admission",
    )
    op.create_table(
        "reminders",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("milestone_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_version", sa.Integer(), nullable=False),
        sa.Column("offset_days", sa.Integer(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=160), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["milestone_id"],
            ["admission.milestones.id"],
            name=op.f("fk_reminders_milestone_id_milestones"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminders")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_reminders_dedupe_key")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_reminders_student_id"),
        "reminders",
        ["student_id"],
        unique=False,
        schema="admission",
    )
    _seed_builtin_roles()


def _seed_builtin_roles() -> None:
    """Insert the built-in sub-roles (a frozen copy of BUILTIN_ROLES)."""
    table = sa.table(
        "staff_roles",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("name", sa.String()),
        sa.column("name_i18n", postgresql.JSONB()),
        sa.column("permissions", postgresql.ARRAY(sa.Text())),
        sa.column("is_builtin", sa.Boolean()),
        schema="admission",
    )
    op.bulk_insert(
        table,
        [
            {
                "id": uuid7(),
                "key": key,
                "kind": kind,
                "name": names[2],
                "name_i18n": {"uz": names[0], "ru": names[1], "en": names[2]},
                "permissions": list(permissions),
                "is_builtin": True,
            }
            for key, kind, names, permissions in _BUILTIN_ROLES
        ],
    )


def downgrade() -> None:
    """Drop the whole schema (the module owns nothing outside it)."""
    op.execute("DROP SCHEMA IF EXISTS admission CASCADE")
