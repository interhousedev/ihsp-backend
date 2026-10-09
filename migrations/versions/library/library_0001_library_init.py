"""library init

Revision ID: library_0001
Revises:
Create Date: 2026-10-08 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "library_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("library",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS library")
    # Trigram similarity on titles (typos and Uzbek word endings).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "annotations",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "highlight",
                "note",
                "bookmark",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "locator",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "color",
            sa.Enum(
                "yellow",
                "green",
                "blue",
                "pink",
                name="color",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="yellow",
            nullable=False,
        ),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_annotations")),
        sa.UniqueConstraint("user_id", "client_id", name="uq_annotations_user_id"),
        schema="library",
    )
    op.create_table(
        "book_plans",
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("year_of_study", sa.SmallInteger(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "sections",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_book_plans")),
        sa.UniqueConstraint(
            "subject_id", "year_of_study", "item_id", name="uq_book_plans_subject_id"
        ),
        schema="library",
    )
    op.create_table(
        "book_suggestions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "new",
                "accepted",
                "declined",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="new",
            nullable=False,
        ),
        sa.Column("handled_by", sa.Uuid(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_book_suggestions")),
        schema="library",
    )
    op.create_table(
        "collections",
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column(
            "title",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "description",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("cover_file_id", sa.Uuid(), nullable=True),
        sa.Column(
            "position", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "published", sa.Boolean(), server_default=sa.text("false"), nullable=False
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collections")),
        sa.UniqueConstraint("slug", name="uq_collections_slug"),
        schema="library",
    )
    op.create_table(
        "external_feeds",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "unilibrary", name="source", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "max_items", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("estimate", sa.Integer(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=True),
        sa.Column("last_count", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_feeds")),
        schema="library",
    )
    op.create_table(
        "external_field_map",
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "unilibrary", name="source", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("external_field_id", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint(
            "subject_id",
            "source",
            "external_field_id",
            name=op.f("pk_external_field_map"),
        ),
        schema="library",
    )
    op.create_table(
        "item_stats",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("opens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("readers", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "offline_saves", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
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
        sa.PrimaryKeyConstraint("item_id", "day", name=op.f("pk_item_stats")),
        schema="library",
    )
    op.create_table(
        "items",
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "external",
                "book",
                "material",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "type",
            sa.Enum(
                "textbook",
                "manual",
                "fiction",
                "poetry",
                "drama",
                "nonfiction",
                "reference",
                "dictionary",
                "lab_manual",
                "problem_book",
                "article",
                "teaching_material",
                "presentation",
                "worksheet",
                "lecture_notes",
                "notes",
                "practice_set",
                "formula_sheet",
                "other",
                name="type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "title_alt",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("subtitle", sa.String(length=255), nullable=True),
        sa.Column(
            "authors",
            sa.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column(
            "author_label", sa.String(length=255), server_default="", nullable=False
        ),
        sa.Column(
            "language",
            sa.Enum(
                "uz_latn",
                "uz_cyrl",
                "ru",
                "en",
                "qq",
                "other",
                name="language",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("year_published", sa.SmallInteger(), nullable=True),
        sa.Column("publisher", sa.String(length=255), nullable=True),
        sa.Column("isbn", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cover_file_id", sa.Uuid(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column(
            "years_of_study",
            sa.ARRAY(sa.SmallInteger()),
            server_default=sa.text("'{}'::smallint[]"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "pending_review",
                "changes_requested",
                "published",
                "held",
                "rejected",
                "unpublished",
                "gone",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("status_reason", sa.String(length=40), nullable=True),
        sa.Column("status_note", sa.Text(), nullable=True),
        sa.Column(
            "visibility",
            sa.Enum(
                "public",
                "lyceum",
                "hidden",
                name="visibility",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "download_allowed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "has_text", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("search_text", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(search_text, ''))", persisted=True
            ),
            nullable=False,
        ),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column(
            "open_reports", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
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
            "kind <> 'external' OR cover_file_id IS NULL",
            name=op.f("ck_items_external_no_file"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
        sa.UniqueConstraint("slug", name="uq_items_slug"),
        schema="library",
    )
    op.create_table(
        "lesson_item_refs",
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("section_label", sa.String(length=200), nullable=False),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("set_by", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lesson_item_refs")),
        schema="library",
    )
    op.create_table(
        "reading_lists",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "scope",
            sa.Enum(
                "subject",
                "groups",
                "school",
                name="scope",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column(
            "group_ids",
            sa.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
        sa.Column("year_of_study", sa.SmallInteger(), nullable=True),
        sa.Column("academic_year", sa.String(length=9), nullable=True),
        sa.Column("term_half", sa.SmallInteger(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "published",
                "archived",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="draft",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reading_lists")),
        schema="library",
    )
    op.create_table(
        "reading_progress",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column(
            "locator",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "percent",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "seconds_read", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("client_ts", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("user_id", "item_id", name=op.f("pk_reading_progress")),
        schema="library",
    )
    op.create_table(
        "sanctions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "warning",
                "upload_ban",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column("set_by", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sanctions")),
        schema="library",
    )
    op.create_table(
        "shelf_entries",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "want",
                "reading",
                "done",
                name="state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shelf_entries")),
        sa.UniqueConstraint("user_id", "item_id", name="uq_shelf_entries_user_id"),
        schema="library",
    )
    op.create_table(
        "topics",
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "name",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column(
            "position", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("year_of_study", sa.SmallInteger(), nullable=True),
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
            ["parent_id"],
            ["library.topics.id"],
            name=op.f("fk_topics_parent_id_topics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topics")),
        sa.UniqueConstraint(
            "subject_id",
            "parent_id",
            "slug",
            name="uq_topics_subject_id",
            postgresql_nulls_not_distinct=True,
        ),
        schema="library",
    )
    op.create_table(
        "book_details",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "rights",
            sa.Enum(
                "public_domain",
                "open_license",
                "permission",
                "official",
                name="rights",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("licence", sa.String(length=40), nullable=True),
        sa.Column(
            "rights_basis",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("rights_proof_file_id", sa.Uuid(), nullable=True),
        sa.Column("rights_checked_by", sa.Uuid(), nullable=True),
        sa.Column("rights_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "translators",
            sa.ARRAY(sa.String()),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
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
            ["item_id"],
            ["library.items.id"],
            name=op.f("fk_book_details_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", name=op.f("pk_book_details")),
        schema="library",
    )
    op.create_table(
        "collection_items",
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "position", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
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
            ["collection_id"],
            ["library.collections.id"],
            name=op.f("fk_collection_items_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "collection_id", "item_id", name=op.f("pk_collection_items")
        ),
        schema="library",
    )
    op.create_table(
        "external_details",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "unilibrary", name="source", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=40), nullable=False),
        sa.Column("category", sa.SmallInteger(), nullable=False),
        sa.Column(
            "access",
            sa.Enum(
                "open",
                "partial",
                "closed",
                name="access",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "type_name",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "field_name",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "language_name",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("view_url", sa.Text(), nullable=False),
        sa.Column("snapshot_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("feed_id", sa.Uuid(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gone_at", sa.DateTime(timezone=True), nullable=True),
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
            ["item_id"],
            ["library.items.id"],
            name=op.f("fk_external_details_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", name=op.f("pk_external_details")),
        sa.UniqueConstraint("source", "external_id", name="uq_external_details_source"),
        schema="library",
    )
    op.create_table(
        "item_events",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "created",
                "submitted",
                "approved",
                "changes_requested",
                "rejected",
                "held",
                "restored",
                "unpublished",
                "edited",
                "version_added",
                "hidden",
                "rights_changed",
                "synced",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
            ["item_id"],
            ["library.items.id"],
            name=op.f("fk_item_events_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", "seq", name=op.f("pk_item_events")),
        schema="library",
    )
    op.create_table(
        "item_files",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column(
            "format",
            sa.Enum(
                "pdf",
                "epub",
                "md",
                "txt",
                "docx",
                "pptx",
                name="format",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "readable", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "text_status",
            sa.Enum(
                "none",
                "pending",
                "ready",
                "no_text",
                "failed",
                name="text_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="none",
            nullable=False,
        ),
        sa.Column(
            "toc",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("sha256", sa.CHAR(length=64), nullable=True),
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
            ["item_id"],
            ["library.items.id"],
            name=op.f("fk_item_files_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", "file_id", name=op.f("pk_item_files")),
        schema="library",
    )
    op.create_table(
        "item_pages",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_norm", sa.Text(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple', coalesce(text_norm, ''))", persisted=True
            ),
            nullable=False,
        ),
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
            ["item_id"],
            ["library.items.id"],
            name=op.f("fk_item_pages_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "item_id", "file_id", "page", name=op.f("pk_item_pages")
        ),
        schema="library",
    )
    op.create_table(
        "item_reports",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("reporter_id", sa.Uuid(), nullable=False),
        sa.Column("reporter_role", sa.String(length=20), nullable=True),
        sa.Column(
            "reason",
            sa.Enum(
                "wrong_content",
                "copyright",
                "inappropriate",
                "personal_data",
                "exam_leak",
                "spam",
                "other",
                name="reason",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("text", sa.String(length=500), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "upheld",
                "dismissed",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("handled_by", sa.Uuid(), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=True),
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
            ["item_id"],
            ["library.items.id"],
            name=op.f("fk_item_reports_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_item_reports")),
        schema="library",
    )
    op.create_table(
        "item_subjects",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column(
            "year_of_study",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum(
                "textbook",
                "core",
                "supplementary",
                "reference",
                name="role",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="supplementary",
            nullable=False,
        ),
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
            ["item_id"],
            ["library.items.id"],
            name=op.f("fk_item_subjects_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "item_id", "subject_id", "year_of_study", name=op.f("pk_item_subjects")
        ),
        schema="library",
    )
    op.create_table(
        "item_topics",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=False),
        sa.Column(
            "page_from", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column(
            "position", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
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
            ["item_id"],
            ["library.items.id"],
            name=op.f("fk_item_topics_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["library.topics.id"],
            name=op.f("fk_item_topics_topic_id_topics"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "item_id", "topic_id", "page_from", name=op.f("pk_item_topics")
        ),
        schema="library",
    )
    op.create_table(
        "material_details",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column(
            "uploader_role",
            sa.Enum(
                "student",
                "teacher",
                "librarian",
                "admin",
                name="uploader_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("uploader_name", sa.String(length=80), nullable=False),
        sa.Column(
            "uploader_cohort", sa.String(length=20), server_default="", nullable=False
        ),
        sa.Column(
            "licence",
            sa.Enum(
                "all_rights_reserved",
                "cc_by",
                "cc_by_sa",
                "cc_by_nc",
                "cc_by_nc_sa",
                name="licence",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "approval",
            sa.Enum(
                "auto_teacher",
                "librarian",
                "admin",
                name="approval",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_message", sa.Text(), nullable=True),
        sa.Column(
            "scan",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
            ["item_id"],
            ["library.items.id"],
            name=op.f("fk_material_details_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", name=op.f("pk_material_details")),
        schema="library",
    )
    op.create_table(
        "reading_list_items",
        sa.Column("list_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "importance",
            sa.Enum(
                "essential",
                "recommended",
                "further",
                name="importance",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="recommended",
            nullable=False,
        ),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("week_label", sa.String(length=40), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
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
            "item_id IS NOT NULL OR url IS NOT NULL",
            name=op.f("ck_reading_list_items_item_or_url"),
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["library.reading_lists.id"],
            name=op.f("fk_reading_list_items_list_id_reading_lists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "list_id", "position", name=op.f("pk_reading_list_items")
        ),
        schema="library",
    )
    op.create_index(
        "ix_annotations_user_id_item_id_updated_at",
        "annotations",
        ["user_id", "item_id", "updated_at"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_book_suggestions_status_created_at",
        "book_suggestions",
        ["status", "created_at"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_items_content_hash",
        "items",
        ["content_hash"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_items_kind_status_visibility",
        "items",
        ["kind", "status", "visibility"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_items_owner_id_created_at",
        "items",
        ["owner_id", "created_at"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_items_search_vector",
        "items",
        ["search_vector"],
        unique=False,
        schema="library",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_items_status_updated_at",
        "items",
        ["status", "updated_at"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_items_title_trgm",
        "items",
        ["title"],
        unique=False,
        schema="library",
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_lesson_item_refs_lesson_id",
        "lesson_item_refs",
        ["lesson_id"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_reading_lists_group_ids",
        "reading_lists",
        ["group_ids"],
        unique=False,
        schema="library",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_reading_lists_owner_id",
        "reading_lists",
        ["owner_id"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_reading_lists_subject_id_status",
        "reading_lists",
        ["subject_id", "status"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_reading_progress_user_id_opened_at",
        "reading_progress",
        ["user_id", "opened_at"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_sanctions_user_id_until",
        "sanctions",
        ["user_id", "until"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_shelf_entries_item_id",
        "shelf_entries",
        ["item_id"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_shelf_entries_user_id_state",
        "shelf_entries",
        ["user_id", "state"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_topics_subject_id_position",
        "topics",
        ["subject_id", "position"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_collection_items_item_id",
        "collection_items",
        ["item_id"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_external_details_fetched_at",
        "external_details",
        ["fetched_at"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_external_details_gone_at",
        "external_details",
        ["gone_at"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_item_files_primary",
        "item_files",
        ["item_id"],
        unique=True,
        schema="library",
        postgresql_where=sa.text("is_primary"),
    )
    op.create_index(
        "ix_item_files_sha256", "item_files", ["sha256"], unique=False, schema="library"
    )
    op.create_index(
        "ix_item_pages_search_vector",
        "item_pages",
        ["search_vector"],
        unique=False,
        schema="library",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_item_reports_open_unique",
        "item_reports",
        ["item_id", "reporter_id", "reason"],
        unique=True,
        schema="library",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_item_reports_status_created_at",
        "item_reports",
        ["status", "created_at"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_item_subjects_subject_id",
        "item_subjects",
        ["subject_id"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_item_topics_topic_id",
        "item_topics",
        ["topic_id"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_material_details_uploader_id_submitted_at",
        "material_details",
        ["uploader_id", "submitted_at"],
        unique=False,
        schema="library",
    )
    op.create_index(
        "ix_reading_list_items_item_id",
        "reading_list_items",
        ["item_id"],
        unique=False,
        schema="library",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("reading_list_items", schema="library")
    op.drop_table("material_details", schema="library")
    op.drop_table("item_topics", schema="library")
    op.drop_table("item_subjects", schema="library")
    op.drop_table("item_reports", schema="library")
    op.drop_table("item_pages", schema="library")
    op.drop_table("item_files", schema="library")
    op.drop_table("item_events", schema="library")
    op.drop_table("external_details", schema="library")
    op.drop_table("collection_items", schema="library")
    op.drop_table("book_details", schema="library")
    op.drop_table("topics", schema="library")
    op.drop_table("shelf_entries", schema="library")
    op.drop_table("sanctions", schema="library")
    op.drop_table("reading_progress", schema="library")
    op.drop_table("reading_lists", schema="library")
    op.drop_table("lesson_item_refs", schema="library")
    op.drop_table("items", schema="library")
    op.drop_table("item_stats", schema="library")
    op.drop_table("external_field_map", schema="library")
    op.drop_table("external_feeds", schema="library")
    op.drop_table("collections", schema="library")
    op.drop_table("book_suggestions", schema="library")
    op.drop_table("book_plans", schema="library")
    op.drop_table("annotations", schema="library")
    op.execute("DROP SCHEMA IF EXISTS library")
