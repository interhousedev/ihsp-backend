"""Sharing files: grants and links.

Revision ID: files_0004
Revises: files_0003
Create Date: 2026-11-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "files_0004"
down_revision: str | Sequence[str] | None = "files_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "file_shares",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("via", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "via IN ('direct', 'link')", name=op.f("ck_file_shares_via")
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.files.id"],
            name=op.f("fk_file_shares_file_id_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("file_id", "user_id", name=op.f("pk_file_shares")),
        schema="files",
    )
    op.create_index(
        "ix_file_shares_user_id", "file_shares", ["user_id"], schema="files"
    )
    op.create_table(
        "file_share_links",
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.files.id"],
            name=op.f("fk_file_share_links_file_id_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("file_id", name=op.f("pk_file_share_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_file_share_links_token_hash")),
        schema="files",
    )


def downgrade() -> None:
    """Downgrade schema (every grant and link is lost)."""
    op.drop_table("file_share_links", schema="files")
    op.drop_table("file_shares", schema="files")
