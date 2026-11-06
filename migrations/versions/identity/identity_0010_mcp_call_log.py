"""MCP call log.

Revision ID: identity_0010
Revises: identity_0009
Create Date: 2026-11-05 09:00:00.000000

One redacted row per MCP tool call. ``connector_id`` has no foreign key and the name is
copied, so a trace stays readable after its connector is deleted.
"""

from collections.abc import Sequence

from app.modules.identity.infrastructure.orm.types import InetStr

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "identity_0010"
down_revision: str | Sequence[str] | None = "identity_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create id.mcp_call_log and its indexes."""
    op.create_table(
        "mcp_call_log",
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
        sa.Column("connector_id", sa.Uuid(), nullable=True),
        sa.Column("connector_name", sa.String(length=255), nullable=True),
        sa.Column("client_id", sa.String(length=255), nullable=True),
        sa.Column("server", sa.String(length=16), nullable=False),
        sa.Column("tool", sa.String(length=100), nullable=False),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_id", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=True),
        sa.Column("result_summary", postgresql.JSONB(), nullable=True),
        sa.Column("ip", InetStr(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["id.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="id",
    )
    for name, columns in (
        ("ix_mcp_call_log_user_id_created_at", ["user_id", "created_at"]),
        ("ix_mcp_call_log_connector_id_created_at", ["connector_id", "created_at"]),
        ("ix_mcp_call_log_created_at", ["created_at"]),
        ("ix_mcp_call_log_outcome_created_at", ["outcome", "created_at"]),
    ):
        op.create_index(name, "mcp_call_log", columns, schema="id")


def downgrade() -> None:
    """Drop id.mcp_call_log."""
    op.drop_table("mcp_call_log", schema="id")
