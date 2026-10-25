"""Hold a login cue while its registration runs.

Revision ID: identity_0009
Revises: identity_0008
Create Date: 2026-10-26 09:00:00.000000

``reserved_until`` is set by a conditional UPDATE before EMIS is asked, so two
concurrent registrations cannot both use one cue. NULL means no hold.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0009"
down_revision: str | Sequence[str] | None = "identity_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the hold column of id.login_cues."""
    op.add_column(
        "login_cues",
        sa.Column("reserved_until", sa.DateTime(timezone=True), nullable=True),
        schema="id",
    )


def downgrade() -> None:
    """Remove the hold column of id.login_cues."""
    op.drop_column("login_cues", "reserved_until", schema="id")
