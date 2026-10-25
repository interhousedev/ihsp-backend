"""users.photo_file_id points at the profile photo in the files module.

Revision ID: identity_0004
Revises: identity_0003
Create Date: 2026-10-10 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0004"
down_revision: str | Sequence[str] | None = "identity_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the column (no foreign key: files live in another module)."""
    op.add_column(
        "users",
        sa.Column("photo_file_id", sa.Uuid(), nullable=True),
        schema="id",
    )


def downgrade() -> None:
    """Drop the column; the photo files stay until their own clean-up."""
    op.drop_column("users", "photo_file_id", schema="id")
