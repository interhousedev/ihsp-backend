"""users.password_change_required marks a password set by an administrator.

Revision ID: identity_0003
Revises: identity_0002
Create Date: 2026-10-10 14:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0003"
down_revision: str | Sequence[str] | None = "identity_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the flag; existing users are not asked to change anything."""
    op.add_column(
        "users",
        sa.Column(
            "password_change_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema="id",
    )


def downgrade() -> None:
    """Drop the flag."""
    op.drop_column("users", "password_change_required", schema="id")
