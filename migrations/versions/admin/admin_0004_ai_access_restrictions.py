"""Per-user revocation of the chat and notebook AI.

Revision ID: admin_0004
Revises: admin_0003
Create Date: 2026-10-25 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admin_0004"
down_revision: str | Sequence[str] | None = "admin_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create admin.ai_access_restrictions: one row per user with a revoked scope."""
    op.create_table(
        "ai_access_restrictions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "ai_chat_blocked",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "ai_notebooks_blocked",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
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
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_ai_access_restrictions")),
        schema="admin",
    )


def downgrade() -> None:
    """Drop the revocations."""
    op.drop_table("ai_access_restrictions", schema="admin")
