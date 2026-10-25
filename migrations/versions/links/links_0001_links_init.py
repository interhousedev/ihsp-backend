"""links init

Revision ID: links_0001
Revises:
Create Date: 2026-10-07 17:00:35.388255

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "links_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("links",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS links")
    op.create_table(
        "links",
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "url",
                "file",
                "chat",
                "flashcard_set",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=True),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("lesson_id", sa.Uuid(), nullable=True),
        sa.Column(
            "lesson_role",
            sa.Enum(
                "material",
                "attachment",
                "homework",
                name="lesson_role",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "share_mode",
            sa.Enum(
                "snapshot",
                "live",
                name="share_mode",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("snapshot_seq", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hits", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_by", sa.Uuid(), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_by", sa.Uuid(), nullable=True),
        sa.Column("disabled_reason", sa.String(length=500), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reports", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reports_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slug_released_at", sa.DateTime(timezone=True), nullable=True),
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
            "(kind = 'file') = (file_id IS NOT NULL)", name=op.f("ck_links_file_target")
        ),
        sa.CheckConstraint(
            "(kind = 'url') = (target_url IS NOT NULL)",
            name=op.f("ck_links_url_target"),
        ),
        sa.CheckConstraint(
            "(kind IN ('chat', 'flashcard_set')) = (target_id IS NOT NULL)",
            name=op.f("ck_links_share_target"),
        ),
        sa.CheckConstraint(
            "lesson_id IS NULL OR kind IN ('url', 'file')",
            name=op.f("ck_links_lesson_kind"),
        ),
        sa.CheckConstraint(
            "share_mode IS NULL OR kind = 'chat'", name=op.f("ck_links_share_mode_chat")
        ),
        sa.CheckConstraint(
            "(lesson_id IS NULL) = (lesson_role IS NULL)",
            name=op.f("ck_links_lesson_role_pair"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_links")),
        schema="links",
    )
    op.create_index(
        "ix_links_file_id", "links", ["file_id"], unique=False, schema="links"
    )
    op.create_index(
        "ix_links_kind_target_id",
        "links",
        ["kind", "target_id"],
        unique=False,
        schema="links",
    )
    op.create_index(
        "ix_links_lesson_id",
        "links",
        ["lesson_id"],
        unique=False,
        schema="links",
        postgresql_where=sa.text("lesson_id IS NOT NULL"),
    )
    op.create_index(
        "ix_links_owner_id_kind",
        "links",
        ["owner_id", "kind"],
        unique=False,
        schema="links",
    )
    op.create_index(
        "ix_links_slug_active",
        "links",
        ["slug"],
        unique=True,
        schema="links",
        postgresql_where=sa.text("slug_released_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_links_slug_active",
        table_name="links",
        schema="links",
        postgresql_where=sa.text("slug_released_at IS NULL"),
    )
    op.drop_index("ix_links_owner_id_kind", table_name="links", schema="links")
    op.drop_index(
        "ix_links_lesson_id",
        table_name="links",
        schema="links",
        postgresql_where=sa.text("lesson_id IS NOT NULL"),
    )
    op.drop_index("ix_links_kind_target_id", table_name="links", schema="links")
    op.drop_index("ix_links_file_id", table_name="links", schema="links")
    op.drop_table("links", schema="links")
    op.execute("DROP SCHEMA IF EXISTS links CASCADE")
