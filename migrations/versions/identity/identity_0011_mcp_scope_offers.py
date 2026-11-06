"""MCP scope offers and extra scopes of connectors.

Revision ID: identity_0011
Revises: identity_0010
Create Date: 2026-11-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0011"
down_revision: str | Sequence[str] | None = "identity_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add id.mcp_scope_offers and mcp_connectors.extra_scopes."""
    op.add_column(
        "mcp_connectors",
        sa.Column(
            "extra_scopes",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        schema="id",
    )
    op.create_table(
        "mcp_scope_offers",
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
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("connector_ids", sa.ARRAY(sa.Uuid()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "granted",
                "declined",
                "expired",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["id.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "release_id", name="uq_mcp_scope_offers_user"),
        sa.UniqueConstraint("token_hash", name="uq_mcp_scope_offers_token_hash"),
        schema="id",
    )
    op.create_index(
        "ix_mcp_scope_offers_status_expires_at",
        "mcp_scope_offers",
        ["status", "expires_at"],
        schema="id",
    )


def downgrade() -> None:
    """Drop the table and the column."""
    op.drop_table("mcp_scope_offers", schema="id")
    op.drop_column("mcp_connectors", "extra_scopes", schema="id")
