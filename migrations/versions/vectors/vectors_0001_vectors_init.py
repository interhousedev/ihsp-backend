"""vectors init: pgvector and the shared embeddings table.

Revision ID: vectors_0001
Revises:
Create Date: 2026-10-09 10:00:00.000000

One vector per (sha256 of a text, model). `halfvec(1024)` keeps each number in
2 bytes: 2 KB per vector against 4 KB for `vector(1024)`, and the same ranking to the
4th decimal. The HNSW index (cosine) is for searches across the whole table (the
library later); a notebook search ranks its own few thousand passages exactly.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "vectors_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("vectors",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS vectors")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE vectors.embeddings (
            content_hash CHAR(64) NOT NULL,
            model TEXT NOT NULL,
            dims INTEGER NOT NULL,
            embedding HALFVEC(1024) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT pk_embeddings PRIMARY KEY (content_hash, model),
            CONSTRAINT ck_embeddings_dims CHECK (dims = vector_dims(embedding))
        )
        """)
    # Floats do not compress and a row fits one page, so keep it out of TOAST.
    op.execute(
        "ALTER TABLE vectors.embeddings ALTER COLUMN embedding SET STORAGE PLAIN"
    )
    op.create_index(
        "ix_embeddings_embedding_hnsw",
        "embeddings",
        ["embedding"],
        schema="vectors",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
    )


def downgrade() -> None:
    """Downgrade schema (the extension stays: other schemas may use it later)."""
    op.drop_index(
        "ix_embeddings_embedding_hnsw",
        table_name="embeddings",
        schema="vectors",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
    )
    op.drop_table("embeddings", schema="vectors")
    op.execute("DROP SCHEMA IF EXISTS vectors")
