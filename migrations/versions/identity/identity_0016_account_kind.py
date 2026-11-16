"""Account kind and phone of a user; admission staff roles need no schema change.

`account_kind` (school, alumni, external, staff) tells EMIS-linked accounts from
invited ones. Existing holders of a staff role become `staff`, the rest `school`.

Revision ID: identity_0016
Revises: identity_0015
Create Date: 2026-11-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0016"
down_revision: str | Sequence[str] | None = "identity_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the columns and backfill staff accounts."""
    op.add_column(
        "users",
        sa.Column(
            "account_kind",
            sa.String(16),
            server_default=sa.text("'school'"),
            nullable=False,
        ),
        schema="id",
    )
    op.add_column(
        "users", sa.Column("phone", sa.String(32), nullable=True), schema="id"
    )
    op.execute(
        "UPDATE id.users SET account_kind = 'staff' WHERE roles && "
        "ARRAY['teacher','admin','librarian','lms_admin','lms_creator']::text[]"
    )


def downgrade() -> None:
    """Drop the columns."""
    op.drop_column("users", "phone", schema="id")
    op.drop_column("users", "account_kind", schema="id")
