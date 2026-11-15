"""Library: folded page text, text source and word boxes for in-item search.

Revision ID: library_0006
Revises: library_0005
Create Date: 2026-11-16 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "library_0006"
down_revision: str | Sequence[str] | None = "library_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add `text_fold`, `source`, `boxes` and a trigram index to `item_pages`."""
    op.add_column("item_pages", sa.Column("text_fold", sa.Text()), schema="library")
    op.add_column(
        "item_pages",
        sa.Column("source", sa.String(16), server_default="text_layer", nullable=False),
        schema="library",
    )
    op.add_column(
        "item_pages",
        sa.Column("boxes", postgresql.JSONB(astext_type=sa.Text())),
        schema="library",
    )
    op.create_index(
        "ix_item_pages_text_fold_trgm",
        "item_pages",
        ["text_fold"],
        schema="library",
        postgresql_using="gin",
        postgresql_ops={"text_fold": "gin_trgm_ops"},
    )


def downgrade() -> None:
    """Drop them."""
    op.drop_index(
        "ix_item_pages_text_fold_trgm", table_name="item_pages", schema="library"
    )
    op.drop_column("item_pages", "boxes", schema="library")
    op.drop_column("item_pages", "source", schema="library")
    op.drop_column("item_pages", "text_fold", schema="library")
