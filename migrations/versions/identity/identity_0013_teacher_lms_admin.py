"""Every teacher is an LMS admin by default.

Revision ID: identity_0013
Revises: identity_0012
Create Date: 2026-11-13 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0013"
down_revision: str | Sequence[str] | None = "identity_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add `lms_admin` to every teacher that lacks it (idempotent)."""
    op.execute(
        "UPDATE id.users SET roles = array_append(roles, 'lms_admin') "
        "WHERE 'teacher' = ANY(roles) AND NOT ('lms_admin' = ANY(roles))"
    )


def downgrade() -> None:
    """Data migration: the roles stay as they are (an admin may have removed them)."""
