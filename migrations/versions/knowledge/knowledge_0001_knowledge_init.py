"""knowledge init: entries with trigram and full-text search.

Revision ID: knowledge_0001
Revises:
Create Date: 2026-10-19 10:00:00.000000

`key` is stored lower case and unique. `search_vector` is a generated column over key,
title and value (`simple` configuration, no stemming: the platform speaks three
languages). Vectors live in the shared `vectors.embeddings`, found by `content_hash`.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "knowledge_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("knowledge",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the schema, the table and its indexes."""
    op.execute("CREATE SCHEMA IF NOT EXISTS knowledge")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("""
        CREATE TABLE knowledge.entries (
            id uuid NOT NULL,
            key varchar(80) NOT NULL,
            title varchar(200),
            value text NOT NULL,
            tags varchar(40)[] NOT NULL DEFAULT '{}',
            author_id uuid NOT NULL,
            content_hash char(64),
            search_vector tsvector GENERATED ALWAYS AS (
                to_tsvector('simple', key || ' ' || coalesce(title, '') || ' ' || value)
            ) STORED,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_entries PRIMARY KEY (id),
            CONSTRAINT uq_entries_key UNIQUE (key)
        )
        """)
    op.execute(
        "CREATE INDEX ix_entries_key_trgm ON knowledge.entries "
        "USING gin (key gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_entries_value_trgm ON knowledge.entries "
        "USING gin (value gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_entries_search_vector ON knowledge.entries "
        "USING gin (search_vector)"
    )
    op.execute("CREATE INDEX ix_entries_updated_at ON knowledge.entries (updated_at)")


def downgrade() -> None:
    """Drop the schema (the extension stays: other modules use it)."""
    op.execute("DROP SCHEMA knowledge CASCADE")
