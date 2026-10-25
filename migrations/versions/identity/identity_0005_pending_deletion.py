"""Account deletion with a recovery window: status pending_deletion.

Revision ID: identity_0005
Revises: identity_0004
Create Date: 2026-10-14 12:00:00.000000

Accounts deleted before this revision keep status ``deleted``: their files and
EMIS secret were removed at once, so they cannot be restored; the daily purge
anonymizes them 30 days after ``deleted_at`` as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0005"
down_revision: str | Sequence[str] | None = "identity_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASE = "'unregistered', 'pending_activation', 'active', 'blocked', 'deactivated'"
OLD = f"{_BASE}, 'deleted'"
NEW = f"{_BASE}, 'pending_deletion', 'deleted'"


def _replace_check(values: str) -> None:
    name = op.f("ck_users_status")
    op.drop_constraint(name, "users", schema="id", type_="check")
    op.create_check_constraint(name, "users", f"status IN ({values})", schema="id")


def upgrade() -> None:
    """Allow ``pending_deletion`` and remember when the deletion was requested."""
    _replace_check(NEW)
    op.add_column(
        "users",
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        schema="id",
    )


def downgrade() -> None:
    """Restore pending accounts (nothing was removed yet), drop the column."""
    op.execute(
        "UPDATE id.users SET status = 'active' WHERE status = 'pending_deletion'"
    )
    op.drop_column("users", "deletion_requested_at", schema="id")
    _replace_check(OLD)
