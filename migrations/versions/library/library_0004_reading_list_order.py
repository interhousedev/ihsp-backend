"""Library: pinned reading lists and their manual order.

Revision ID: library_0004
Revises: library_0003
Create Date: 2026-11-15 12:00:00.000000

Librarians pin a list (`pinned`) and drag lists into a sequence (`sort_order`).
Existing lists keep their old order (newest change first) as the first sequence.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "library_0004"
down_revision: str | Sequence[str] | None = "library_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "reading_lists"
SCHEMA = "library"


def upgrade() -> None:
    """Add the columns and number the existing lists."""
    op.add_column(
        TABLE,
        sa.Column("pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        schema=SCHEMA,
    )
    op.execute("""
        UPDATE library.reading_lists AS l SET sort_order = n.rn
        FROM (
            SELECT id, row_number() OVER (ORDER BY updated_at DESC, id) AS rn
            FROM library.reading_lists
        ) AS n WHERE n.id = l.id
        """)


def downgrade() -> None:
    """Drop them again."""
    op.drop_column(TABLE, "sort_order", schema=SCHEMA)
    op.drop_column(TABLE, "pinned", schema=SCHEMA)
