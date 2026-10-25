"""knowledge audience flags: accessible to guests (off) and to students (on).

Revision ID: knowledge_0002
Revises: knowledge_0001
Create Date: 2026-10-25 10:00:00.000000

Existing entries stay visible to students and hidden from guests, the defaults of
the new columns. Two plain indexes serve the audience filter of the search.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "knowledge_0002"
down_revision: str | Sequence[str] | None = "knowledge_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the two flags with their defaults and index them."""
    op.execute(
        "ALTER TABLE knowledge.entries "
        "ADD COLUMN accessible_to_guest boolean NOT NULL DEFAULT false, "
        "ADD COLUMN accessible_to_student boolean NOT NULL DEFAULT true"
    )
    op.execute(
        "CREATE INDEX ix_entries_guest ON knowledge.entries (accessible_to_guest)"
    )
    op.execute(
        "CREATE INDEX ix_entries_student ON knowledge.entries (accessible_to_student)"
    )


def downgrade() -> None:
    """Drop the indexes and the flags."""
    op.execute("DROP INDEX IF EXISTS knowledge.ix_entries_student")
    op.execute("DROP INDEX IF EXISTS knowledge.ix_entries_guest")
    op.execute(
        "ALTER TABLE knowledge.entries "
        "DROP COLUMN accessible_to_student, DROP COLUMN accessible_to_guest"
    )
