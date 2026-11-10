"""Auto notebook titles that follow the subject name in the reader's language.

Revision ID: notebooks_0016
Revises: notebooks_0015
Create Date: 2026-11-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0016"
down_revision: str | Sequence[str] | None = "notebooks_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "notebooks",
        sa.Column("subject_title_suffix", sa.String(80), nullable=True),
        schema="notebooks",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("notebooks", "subject_title_suffix", schema="notebooks")
