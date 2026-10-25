"""notebooks init

Revision ID: notebooks_0001
Revises:
Create Date: 2026-10-08 09:53:38.771220

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "notebooks_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("notebooks",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS notebooks")
    # Trigram similarity for lexical retrieval (typos and Uzbek word endings).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "notebooks",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column(
            "title_auto", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("emoji", sa.String(length=16), nullable=True),
        sa.Column(
            "emoji_auto", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "chat_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(
                '\'{"style": "default", "custom_prompt": null, "length": "default", "language": "auto"}\'::jsonb'
            ),
            nullable=False,
        ),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "summary_status",
            sa.Enum(
                "none",
                "stale",
                "building",
                "ready",
                "failed",
                name="summary_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
        sa.Column("summary_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "source_count",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "char_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notebooks")),
        schema="notebooks",
    )
    op.create_index(
        "ix_notebooks_owner_id_pinned_last_opened_at",
        "notebooks",
        [
            "owner_id",
            sa.literal_column("pinned DESC"),
            sa.literal_column("last_opened_at DESC NULLS LAST"),
        ],
        unique=False,
        schema="notebooks",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_notebooks_summary_due_at",
        "notebooks",
        ["summary_due_at"],
        unique=False,
        schema="notebooks",
        postgresql_where=sa.text("summary_status = 'stale'"),
    )
    op.create_table(
        "artifacts",
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "report",
                "mind_map",
                "flashcards",
                "quiz",
                "data_table",
                "slides",
                "infographic",
                "audio_overview",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("format", sa.String(length=20), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "generating",
                "ready",
                "failed",
                "canceled",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column(
            "source_ids",
            sa.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "source_map",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "sampled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("refs_index", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("tokens_cached", sa.Integer(), nullable=True),
        sa.Column("weighted", sa.Integer(), nullable=True),
        sa.Column("cost_micro", sa.BigInteger(), nullable=True),
        sa.Column(
            "attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("progress", sa.SmallInteger(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("flashcard_set_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["notebook_id"],
            ["notebooks.notebooks.id"],
            name=op.f("fk_artifacts_notebook_id_notebooks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
        schema="notebooks",
    )
    op.create_index(
        "ix_artifacts_notebook_id_created_at",
        "artifacts",
        ["notebook_id", sa.literal_column("created_at DESC")],
        unique=False,
        schema="notebooks",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_artifacts_owner_id_created_at",
        "artifacts",
        ["owner_id", "created_at"],
        unique=False,
        schema="notebooks",
    )
    op.create_index(
        "ix_artifacts_status",
        "artifacts",
        ["status"],
        unique=False,
        schema="notebooks",
        postgresql_where=sa.text("status IN ('queued', 'generating')"),
    )
    op.create_table(
        "messages",
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "assistant",
                name="role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("tokens_cached", sa.Integer(), nullable=True),
        sa.Column("weighted", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("feedback", sa.SmallInteger(), nullable=True),
        sa.Column(
            "stopped", sa.Boolean(), server_default=sa.text("false"), nullable=False
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
            ["notebook_id"],
            ["notebooks.notebooks.id"],
            name=op.f("fk_messages_notebook_id_notebooks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint(
            "notebook_id", "user_id", "seq", name="uq_messages_notebook_id_user_id_seq"
        ),
        schema="notebooks",
    )
    op.create_table(
        "sources",
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "file",
                "chat",
                "lesson_resource",
                "flashcard_set",
                "lms_step",
                "text",
                "note",
                "url",
                "web_result",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "ref",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("ref_key", sa.String(length=300), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("origin", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "selected", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "ready",
                "failed",
                "unavailable",
                "stale",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("failure", sa.String(length=32), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=True),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("upstream_version", sa.String(length=64), nullable=True),
        sa.Column(
            "word_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "char_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "token_estimate", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "passage_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("guide", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "guide_status",
            sa.Enum(
                "none",
                "building",
                "ready",
                "failed",
                name="guide_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
        sa.Column("text_synced_at", sa.DateTime(timezone=True), nullable=True),
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
            ["notebook_id"],
            ["notebooks.notebooks.id"],
            name=op.f("fk_sources_notebook_id_notebooks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        schema="notebooks",
    )
    op.create_index(
        "ix_sources_notebook_id_position",
        "sources",
        ["notebook_id", "position"],
        unique=False,
        schema="notebooks",
    )
    op.create_index(
        "ix_sources_owner_id", "sources", ["owner_id"], unique=False, schema="notebooks"
    )
    op.create_index(
        "ix_sources_ref_key",
        "sources",
        ["ref_key"],
        unique=False,
        schema="notebooks",
        postgresql_where=sa.text("ref_key IS NOT NULL"),
    )
    op.create_index(
        "uq_sources_notebook_id_ref_key",
        "sources",
        ["notebook_id", "ref_key"],
        unique=True,
        schema="notebooks",
        postgresql_where=sa.text("ref_key IS NOT NULL"),
    )
    op.create_table(
        "artifact_assets",
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "audio_turn", name="kind", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
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
            ["artifact_id"],
            ["notebooks.artifacts.id"],
            name=op.f("fk_artifact_assets_artifact_id_artifacts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_assets")),
        sa.UniqueConstraint(
            "artifact_id", "kind", "idx", name="uq_artifact_assets_artifact_id_kind_idx"
        ),
        schema="notebooks",
    )
    op.create_table(
        "artifact_progress",
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            ["artifact_id"],
            ["notebooks.artifacts.id"],
            name=op.f("fk_artifact_progress_artifact_id_artifacts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "artifact_id", "user_id", name=op.f("pk_artifact_progress")
        ),
        schema="notebooks",
    )
    op.create_table(
        "passages",
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("heading", sa.String(length=200), nullable=True),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('russian', text) || to_tsvector('simple', text)",
                persisted=True,
            ),
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
            ["source_id"],
            ["notebooks.sources.id"],
            name=op.f("fk_passages_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_passages")),
        sa.UniqueConstraint("source_id", "seq", name="uq_passages_source_id_seq"),
        schema="notebooks",
    )
    op.create_index(
        "ix_passages_notebook_id_source_id_seq",
        "passages",
        ["notebook_id", "source_id", "seq"],
        unique=False,
        schema="notebooks",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_passages_notebook_id_source_id_seq",
        table_name="passages",
        schema="notebooks",
    )
    op.drop_table("passages", schema="notebooks")
    op.drop_table("artifact_progress", schema="notebooks")
    op.drop_table("artifact_assets", schema="notebooks")
    op.drop_index(
        "uq_sources_notebook_id_ref_key",
        table_name="sources",
        schema="notebooks",
        postgresql_where=sa.text("ref_key IS NOT NULL"),
    )
    op.drop_index(
        "ix_sources_ref_key",
        table_name="sources",
        schema="notebooks",
        postgresql_where=sa.text("ref_key IS NOT NULL"),
    )
    op.drop_index("ix_sources_owner_id", table_name="sources", schema="notebooks")
    op.drop_index(
        "ix_sources_notebook_id_position", table_name="sources", schema="notebooks"
    )
    op.drop_table("sources", schema="notebooks")
    op.drop_table("messages", schema="notebooks")
    op.drop_index(
        "ix_artifacts_status",
        table_name="artifacts",
        schema="notebooks",
        postgresql_where=sa.text("status IN ('queued', 'generating')"),
    )
    op.drop_index(
        "ix_artifacts_owner_id_created_at", table_name="artifacts", schema="notebooks"
    )
    op.drop_index(
        "ix_artifacts_notebook_id_created_at",
        table_name="artifacts",
        schema="notebooks",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("artifacts", schema="notebooks")
    op.drop_index(
        "ix_notebooks_summary_due_at",
        table_name="notebooks",
        schema="notebooks",
        postgresql_where=sa.text("summary_status = 'stale'"),
    )
    op.drop_index(
        "ix_notebooks_owner_id_pinned_last_opened_at",
        table_name="notebooks",
        schema="notebooks",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("notebooks", schema="notebooks")
    # The extension is left in place: other schemas of the database may use it.
    op.execute("DROP SCHEMA IF EXISTS notebooks")
