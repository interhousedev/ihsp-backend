"""Cancelled notification status.

Revision ID: notify_0020
Revises: notify_0019
Create Date: 2026-11-16 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notify_0020"
down_revision: str | Sequence[str] | None = "notify_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = ("pending", "sending", "sent", "partial", "failed", "skipped")
CONSTRAINT = "ck_notifications_status"


def _replace_constraint(statuses: tuple[str, ...]) -> None:
    """Resize ``status`` to the longest value and re-create its CHECK constraint.

    SQLAlchemy stores a non-native enum as ``VARCHAR(longest value)``, so
    ``cancelled`` needs the column widened as well.
    """
    op.execute(f"ALTER TABLE notify.notifications DROP CONSTRAINT {CONSTRAINT}")
    op.alter_column(
        "notifications",
        "status",
        existing_type=sa.String(),
        type_=sa.String(length=max(len(value) for value in statuses)),
        existing_nullable=False,
        schema="notify",
    )
    values = ", ".join(f"'{value}'" for value in statuses)
    op.execute(
        f"ALTER TABLE notify.notifications "
        f"ADD CONSTRAINT {CONSTRAINT} CHECK (status IN ({values}))"
    )


def upgrade() -> None:
    """Allow the cancelled status."""
    _replace_constraint((*OLD_STATUSES, "cancelled"))


def downgrade() -> None:
    """Forbid it again; cancelled rows were never sent and are deleted."""
    op.execute("DELETE FROM notify.notifications WHERE status = 'cancelled'")
    _replace_constraint(OLD_STATUSES)
