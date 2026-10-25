"""files init

Revision ID: files_0001
Revises:
Create Date: 2026-10-07 17:00:31.006133

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "files_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("files",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS files")
    op.create_table(
        "files",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "student",
                "staff",
                "course",
                "mail",
                "system",
                name="scope",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "ready",
                "rejected",
                "deleted",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("reject_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("text_bytes", sa.Integer(), nullable=True),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("term_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
        sa.UniqueConstraint("key", name="uq_files_key"),
        schema="files",
    )
    op.create_index(
        "ix_files_expires_at", "files", ["expires_at"], unique=False, schema="files"
    )
    op.create_index(
        "ix_files_owner_id_scope_term_id",
        "files",
        ["owner_id", "scope", "term_id"],
        unique=False,
        schema="files",
    )
    op.create_index(
        "ix_files_search_vector",
        "files",
        ["search_vector"],
        unique=False,
        schema="files",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_files_status_created_at",
        "files",
        ["status", "created_at"],
        unique=False,
        schema="files",
    )
    op.create_index(
        "ix_files_term_id_status",
        "files",
        ["term_id", "status"],
        unique=False,
        schema="files",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_files_term_id_status", table_name="files", schema="files")
    op.drop_index("ix_files_status_created_at", table_name="files", schema="files")
    op.drop_index(
        "ix_files_search_vector",
        table_name="files",
        schema="files",
        postgresql_using="gin",
    )
    op.drop_index("ix_files_owner_id_scope_term_id", table_name="files", schema="files")
    op.drop_index("ix_files_expires_at", table_name="files", schema="files")
    op.drop_table("files", schema="files")
    op.execute("DROP SCHEMA IF EXISTS files CASCADE")
