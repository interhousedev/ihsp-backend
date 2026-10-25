"""auto notebooks and the shared content layer

Two parts in one revision (one head for the notebooks branch):

* Auto notebooks: `origin`, `subject_id`, `lesson_id`, `auto_settings` and
  `auto_synced_at` on notebooks, with their constraint and indexes.
* Shared documents: passages move from sources to documents (one document per
  distinct normalized text), so thirty students who hold the same lesson file share
  one set of passages, one guide and one summary. Existing data is converted: the
  oldest source of each text keeps its passages as the document's; passages of later
  duplicates are dropped (old citations keep their snapshot) and their sources point
  at the document. Every passage also gets a `content_hash` (sha256 of its text) for
  the values derived from a text, such as embeddings.

Revision ID: notebooks_0002
Revises: notebooks_0001
Create Date: 2026-10-08 16:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "notebooks_0002"
down_revision: str | Sequence[str] | None = "notebooks_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTO_TARGET = (
    "(origin = 'manual' AND subject_id IS NULL AND lesson_id IS NULL "
    "AND auto_settings IS NULL) "
    "OR (origin = 'subject_auto' AND subject_id IS NOT NULL "
    "AND lesson_id IS NULL AND auto_settings IS NOT NULL) "
    "OR (origin = 'lesson_auto' AND lesson_id IS NOT NULL "
    "AND subject_id IS NOT NULL AND auto_settings IS NOT NULL)"
)


def _upgrade_auto() -> None:
    """Auto notebooks: origin, subject, lesson and the sync settings."""
    op.add_column(
        "notebooks",
        sa.Column(
            "origin",
            sa.Enum(
                "manual",
                "subject_auto",
                "lesson_auto",
                name="origin",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
        schema="notebooks",
    )
    op.add_column(
        "notebooks",
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        schema="notebooks",
    )
    op.add_column(
        "notebooks",
        sa.Column("lesson_id", sa.Uuid(), nullable=True),
        schema="notebooks",
    )
    op.add_column(
        "notebooks",
        sa.Column(
            "auto_settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        schema="notebooks",
    )
    op.add_column(
        "notebooks",
        sa.Column("auto_synced_at", sa.DateTime(timezone=True), nullable=True),
        schema="notebooks",
    )
    op.create_check_constraint(
        op.f("ck_notebooks_auto_target"), "notebooks", AUTO_TARGET, schema="notebooks"
    )
    op.create_index(
        "ix_notebooks_owner_id_subject_id_auto",
        "notebooks",
        ["owner_id", "subject_id"],
        unique=True,
        schema="notebooks",
        postgresql_where=sa.text("origin = 'subject_auto' AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_notebooks_owner_id_lesson_id_auto",
        "notebooks",
        ["owner_id", "lesson_id"],
        unique=True,
        schema="notebooks",
        postgresql_where=sa.text("origin = 'lesson_auto' AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_notebooks_subject_id_auto",
        "notebooks",
        ["subject_id"],
        unique=False,
        schema="notebooks",
        postgresql_where=sa.text("origin <> 'manual' AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_notebooks_lesson_id_auto",
        "notebooks",
        ["lesson_id"],
        unique=False,
        schema="notebooks",
        postgresql_where=sa.text("origin = 'lesson_auto' AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_notebooks_auto_synced_at",
        "notebooks",
        ["auto_synced_at"],
        unique=False,
        schema="notebooks",
        postgresql_where=sa.text("origin <> 'manual' AND deleted_at IS NULL"),
    )


def _downgrade_auto() -> None:
    """Remove the auto notebook columns."""
    op.drop_index(
        "ix_notebooks_auto_synced_at",
        table_name="notebooks",
        schema="notebooks",
        postgresql_where=sa.text("origin <> 'manual' AND deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_notebooks_lesson_id_auto",
        table_name="notebooks",
        schema="notebooks",
        postgresql_where=sa.text("origin = 'lesson_auto' AND deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_notebooks_subject_id_auto",
        table_name="notebooks",
        schema="notebooks",
        postgresql_where=sa.text("origin <> 'manual' AND deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_notebooks_owner_id_lesson_id_auto",
        table_name="notebooks",
        schema="notebooks",
        postgresql_where=sa.text("origin = 'lesson_auto' AND deleted_at IS NULL"),
    )
    op.drop_index(
        "ix_notebooks_owner_id_subject_id_auto",
        table_name="notebooks",
        schema="notebooks",
        postgresql_where=sa.text("origin = 'subject_auto' AND deleted_at IS NULL"),
    )
    op.drop_constraint(
        op.f("ck_notebooks_auto_target"), "notebooks", schema="notebooks", type_="check"
    )
    op.drop_column("notebooks", "auto_synced_at", schema="notebooks")
    op.drop_column("notebooks", "auto_settings", schema="notebooks")
    op.drop_column("notebooks", "lesson_id", schema="notebooks")
    op.drop_column("notebooks", "subject_id", schema="notebooks")
    # The CHECK constraint of the enumeration goes with its column.
    op.drop_column("notebooks", "origin", schema="notebooks")


NOW = sa.text("now()")


def _create_shared_tables() -> None:
    op.create_table(
        "documents",
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("content_hash", name="uq_documents_content_hash"),
        schema="notebooks",
    )
    op.create_table(
        "document_aliases",
        sa.Column("alias", sa.String(length=300), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["notebooks.documents.id"],
            name=op.f("fk_document_aliases_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("alias", name=op.f("pk_document_aliases")),
        schema="notebooks",
    )
    op.create_index(
        "ix_document_aliases_document_id",
        "document_aliases",
        ["document_id"],
        unique=False,
        schema="notebooks",
    )
    op.create_table(
        "document_guides",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("guide", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["notebooks.documents.id"],
            name=op.f("fk_document_guides_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "document_id", "language", name=op.f("pk_document_guides")
        ),
        schema="notebooks",
    )
    op.create_table(
        "shared_summaries",
        sa.Column("selection_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hits", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.PrimaryKeyConstraint(
            "selection_hash", "language", name=op.f("pk_shared_summaries")
        ),
        schema="notebooks",
    )
    op.create_table(
        "shared_artifacts",
        sa.Column("cache_key", sa.CHAR(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("format", sa.String(length=20), nullable=True),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("refs_index", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "source_map", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "source_documents",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "sampled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hits", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.PrimaryKeyConstraint("cache_key", name=op.f("pk_shared_artifacts")),
        schema="notebooks",
    )


def _convert_passages_to_documents() -> None:
    """Make one document per distinct text and move the passages onto it."""
    op.execute("""
        CREATE TEMPORARY TABLE _canonical ON COMMIT DROP AS
        SELECT content_hash,
               (array_agg(id ORDER BY created_at, id))[1] AS source_id,
               gen_random_uuid() AS document_id
        FROM notebooks.sources
        WHERE content_hash IS NOT NULL
          AND status IN ('ready', 'stale')
          AND passage_count > 0
        GROUP BY content_hash
        """)
    op.execute("""
        INSERT INTO notebooks.documents
            (id, content_hash, word_count, char_count, token_estimate, passage_count)
        SELECT c.document_id, c.content_hash, s.word_count, s.char_count,
               s.token_estimate, s.passage_count
        FROM _canonical c
        JOIN notebooks.sources s ON s.id = c.source_id
        """)
    op.execute("""
        UPDATE notebooks.sources s
        SET document_id = c.document_id
        FROM _canonical c
        WHERE s.content_hash = c.content_hash
          AND s.status IN ('ready', 'stale')
          AND s.passage_count > 0
        """)
    op.execute("""
        UPDATE notebooks.passages p
        SET document_id = c.document_id
        FROM _canonical c
        WHERE p.source_id = c.source_id
        """)
    op.execute("DELETE FROM notebooks.passages WHERE document_id IS NULL")
    # Files never change: a file id names its text for every later source.
    op.execute("""
        INSERT INTO notebooks.document_aliases (alias, document_id)
        SELECT 'file:' || (s.ref ->> 'file_id'), s.document_id
        FROM notebooks.sources s
        WHERE s.document_id IS NOT NULL AND s.ref ->> 'file_id' IS NOT NULL
        ON CONFLICT (alias) DO NOTHING
        """)
    # A usable source without text cannot be served: read it again.
    op.execute("""
        UPDATE notebooks.sources
        SET status = 'pending', failure = NULL
        WHERE status IN ('ready', 'stale') AND document_id IS NULL
        """)


def _upgrade_shared() -> None:
    """Shared documents: passages move from sources to documents."""
    _create_shared_tables()
    op.add_column(
        "artifacts",
        sa.Column("cache_key", sa.CHAR(length=64), nullable=True),
        schema="notebooks",
    )
    op.add_column(
        "artifacts",
        sa.Column(
            "from_cache", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        schema="notebooks",
    )
    op.add_column(
        "notebooks",
        sa.Column("space_key", sa.String(length=200), nullable=True),
        schema="notebooks",
    )
    op.add_column(
        "sources",
        sa.Column("document_id", sa.Uuid(), nullable=True),
        schema="notebooks",
    )
    op.add_column(
        "passages",
        sa.Column("document_id", sa.Uuid(), nullable=True),
        schema="notebooks",
    )
    op.add_column(
        "passages",
        sa.Column("content_hash", sa.CHAR(length=64), nullable=True),
        schema="notebooks",
    )
    _convert_passages_to_documents()

    op.alter_column("passages", "document_id", nullable=False, schema="notebooks")
    op.execute("""
        UPDATE notebooks.passages
        SET content_hash = encode(sha256(convert_to(text, 'UTF8')), 'hex')
        """)
    op.alter_column("passages", "content_hash", nullable=False, schema="notebooks")
    op.create_index(
        "ix_passages_content_hash",
        "passages",
        ["content_hash"],
        unique=False,
        schema="notebooks",
    )
    op.drop_index(
        op.f("ix_passages_notebook_id_source_id_seq"),
        table_name="passages",
        schema="notebooks",
    )
    op.drop_constraint(
        op.f("uq_passages_source_id_seq"),
        "passages",
        schema="notebooks",
        type_="unique",
    )
    op.drop_constraint(
        op.f("fk_passages_source_id_sources"),
        "passages",
        schema="notebooks",
        type_="foreignkey",
    )
    op.drop_column("passages", "source_id", schema="notebooks")
    op.drop_column("passages", "notebook_id", schema="notebooks")
    op.create_unique_constraint(
        "uq_passages_document_id_seq",
        "passages",
        ["document_id", "seq"],
        schema="notebooks",
    )
    op.create_foreign_key(
        op.f("fk_passages_document_id_documents"),
        "passages",
        "documents",
        ["document_id"],
        ["id"],
        source_schema="notebooks",
        referent_schema="notebooks",
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_sources_document_id_documents"),
        "sources",
        "documents",
        ["document_id"],
        ["id"],
        source_schema="notebooks",
        referent_schema="notebooks",
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_sources_document_id",
        "sources",
        ["document_id"],
        unique=False,
        schema="notebooks",
        postgresql_where=sa.text("document_id IS NOT NULL"),
    )


def _downgrade_shared() -> None:
    """Give every source its own copy of its document's passages again."""
    op.drop_index(
        "ix_sources_document_id",
        table_name="sources",
        schema="notebooks",
        postgresql_where=sa.text("document_id IS NOT NULL"),
    )
    op.drop_constraint(
        op.f("fk_sources_document_id_documents"),
        "sources",
        schema="notebooks",
        type_="foreignkey",
    )
    op.drop_index("ix_passages_content_hash", table_name="passages", schema="notebooks")
    op.drop_column("passages", "content_hash", schema="notebooks")
    op.drop_constraint(
        "uq_passages_document_id_seq", "passages", schema="notebooks", type_="unique"
    )
    op.add_column(
        "passages", sa.Column("source_id", sa.Uuid(), nullable=True), schema="notebooks"
    )
    op.add_column(
        "passages",
        sa.Column("notebook_id", sa.Uuid(), nullable=True),
        schema="notebooks",
    )
    # The oldest source of a document takes the stored passages ...
    op.execute("""
        UPDATE notebooks.passages p
        SET source_id = first.id, notebook_id = first.notebook_id
        FROM (
            SELECT DISTINCT ON (document_id) document_id, id, notebook_id
            FROM notebooks.sources
            WHERE document_id IS NOT NULL
            ORDER BY document_id, created_at, id
        ) first
        WHERE p.document_id = first.document_id
        """)
    # ... every other source of it gets a copy.
    op.execute("""
        INSERT INTO notebooks.passages
            (id, document_id, source_id, notebook_id, seq, text, char_start,
             char_end, page, heading, token_estimate)
        SELECT gen_random_uuid(), p.document_id, s.id, s.notebook_id, p.seq, p.text,
               p.char_start, p.char_end, p.page, p.heading, p.token_estimate
        FROM notebooks.passages p
        JOIN notebooks.sources s ON s.document_id = p.document_id
        WHERE p.source_id IS NOT NULL AND s.id <> p.source_id
        """)
    op.execute("DELETE FROM notebooks.passages WHERE source_id IS NULL")
    op.alter_column("passages", "source_id", nullable=False, schema="notebooks")
    op.alter_column("passages", "notebook_id", nullable=False, schema="notebooks")
    op.drop_constraint(
        op.f("fk_passages_document_id_documents"),
        "passages",
        schema="notebooks",
        type_="foreignkey",
    )
    op.drop_column("passages", "document_id", schema="notebooks")
    op.create_foreign_key(
        op.f("fk_passages_source_id_sources"),
        "passages",
        "sources",
        ["source_id"],
        ["id"],
        source_schema="notebooks",
        referent_schema="notebooks",
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        op.f("uq_passages_source_id_seq"),
        "passages",
        ["source_id", "seq"],
        schema="notebooks",
    )
    op.create_index(
        op.f("ix_passages_notebook_id_source_id_seq"),
        "passages",
        ["notebook_id", "source_id", "seq"],
        unique=False,
        schema="notebooks",
    )
    op.drop_column("sources", "document_id", schema="notebooks")
    op.drop_column("notebooks", "space_key", schema="notebooks")
    op.drop_column("artifacts", "from_cache", schema="notebooks")
    op.drop_column("artifacts", "cache_key", schema="notebooks")
    op.drop_table("shared_artifacts", schema="notebooks")
    op.drop_table("shared_summaries", schema="notebooks")
    op.drop_table("document_guides", schema="notebooks")
    op.drop_index(
        "ix_document_aliases_document_id",
        table_name="document_aliases",
        schema="notebooks",
    )
    op.drop_table("document_aliases", schema="notebooks")
    op.drop_table("documents", schema="notebooks")


def upgrade() -> None:
    """Upgrade schema."""
    _upgrade_auto()
    _upgrade_shared()


def downgrade() -> None:
    """Downgrade schema."""
    _downgrade_shared()
    _downgrade_auto()
