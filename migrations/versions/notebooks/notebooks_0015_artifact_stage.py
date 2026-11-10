"""The step a slide deck pipeline is in while its output generates.

Revision ID: notebooks_0015
Revises: notebooks_0014
Create Date: 2026-11-11 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0015"
down_revision: str | Sequence[str] | None = "notebooks_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "artifacts",
        sa.Column("stage", sa.String(24), nullable=True),
        schema="notebooks",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("artifacts", "stage", schema="notebooks")
