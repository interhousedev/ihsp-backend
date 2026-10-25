"""Administrator edits lock the name and the login against the EMIS sync.

Revision ID: identity_0007
Revises: identity_0006_factors
Create Date: 2026-10-17 12:00:00.000000

Existing accounts start unlocked, so the next EMIS sync behaves as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0007"
down_revision: str | Sequence[str] | None = "identity_0006_factors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the two manual-override flags."""
    for column in ("name_locked", "login_locked"):
        op.add_column(
            "users",
            sa.Column(
                column,
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
            schema="id",
        )


def downgrade() -> None:
    """Drop the flags; the EMIS sync then overwrites names again."""
    op.drop_column("users", "login_locked", schema="id")
    op.drop_column("users", "name_locked", schema="id")
