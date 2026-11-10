"""Personal API tokens.

Revision ID: identity_0012
Revises: identity_0011
Create Date: 2026-11-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0012"
down_revision: str | Sequence[str] | None = "identity_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add id.personal_tokens."""
    op.create_table(
        "personal_tokens",
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
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["id.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hash", name="uq_personal_tokens_hash"),
        schema="id",
    )
    op.create_index(
        "ix_personal_tokens_user_id", "personal_tokens", ["user_id"], schema="id"
    )


def downgrade() -> None:
    """Drop id.personal_tokens."""
    op.drop_table("personal_tokens", schema="id")
