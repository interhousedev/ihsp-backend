"""Library: decisions of book suggestions (reason, created book, decision time).

Revision ID: library_0003
Revises: library_0002
Create Date: 2026-10-17 12:00:00.000000

`/upload/` sends a student's book form with its files as a suggestion; a librarian
approves it into a book (`item_id`) or declines it with a `reason`. `decided_at`
starts the retention after which the files of a declined suggestion are deleted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "library_0003"
down_revision: str | Sequence[str] | None = "library_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "book_suggestions"
SCHEMA = "library"


def upgrade() -> None:
    """Add the decision columns and an index for "my suggestions"."""
    op.add_column(TABLE, sa.Column("reason", sa.Text(), nullable=True), schema=SCHEMA)
    op.add_column(TABLE, sa.Column("item_id", sa.Uuid(), nullable=True), schema=SCHEMA)
    op.add_column(
        TABLE,
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_book_suggestions_user_id_created_at",
        TABLE,
        ["user_id", "created_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Drop them again."""
    op.drop_index(
        "ix_book_suggestions_user_id_created_at", table_name=TABLE, schema=SCHEMA
    )
    for column in ("decided_at", "item_id", "reason"):
        op.drop_column(TABLE, column, schema=SCHEMA)
