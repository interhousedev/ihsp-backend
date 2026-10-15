"""Source URL of imported lesson files.

EMIS materials are downloaded into our storage and attached as file resources; the
new nullable column `source_url` keeps the EMIS address, so the daily re-sync skips
a material it already imported. Downgrading drops the column.

Revision ID: links_0003
Revises: links_0002
Create Date: 2026-10-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "links_0003"
down_revision: str | Sequence[str] | None = "links_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "links", sa.Column("source_url", sa.Text(), nullable=True), schema="links"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("links", "source_url", schema="links")
