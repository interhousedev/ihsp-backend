"""Timestamps on the label tables.

Every table of the models has `created_at` and `updated_at` (README, Models). The
label tables of notebooks_0004 had only some of them: `source_labels` lacked
`updated_at`, `source_label_links` and `source_label_runs` both. Existing rows get the
time of the migration. Downgrading drops the added columns.

Revision ID: notebooks_0006
Revises: notebooks_0005
Create Date: 2026-10-09 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0006"
down_revision: str | Sequence[str] | None = "notebooks_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str) -> sa.Column[sa.DateTime]:
    """A `timestamptz` column that the database fills with `now()`."""
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("source_labels", _timestamp("updated_at"), schema="notebooks")
    for table in ("source_label_links", "source_label_runs"):
        op.add_column(table, _timestamp("created_at"), schema="notebooks")
        op.add_column(table, _timestamp("updated_at"), schema="notebooks")


def downgrade() -> None:
    """Downgrade schema."""
    for table in ("source_label_runs", "source_label_links"):
        op.drop_column(table, "updated_at", schema="notebooks")
        op.drop_column(table, "created_at", schema="notebooks")
    op.drop_column("source_labels", "updated_at", schema="notebooks")
