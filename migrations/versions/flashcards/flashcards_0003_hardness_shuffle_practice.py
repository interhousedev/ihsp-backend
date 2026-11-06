"""card hardness, set shuffle, practice answers

Revision ID: flashcards_0003
Revises: flashcards_0002
Create Date: 2026-11-05 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "flashcards_0003"
down_revision: str | Sequence[str] | None = "flashcards_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "flashcards",
        sa.Column(
            "hardness",
            sa.Enum(
                "easy",
                "medium",
                "hard",
                name="hardness",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'medium'"),
            nullable=False,
        ),
        schema="ai",
    )
    op.add_column(
        "flashcard_sets",
        sa.Column(
            "shuffle", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        schema="ai",
    )
    op.add_column(
        "flashcard_reviews",
        sa.Column(
            "practice", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        schema="ai",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("flashcard_reviews", "practice", schema="ai")
    op.drop_column("flashcard_sets", "shuffle", schema="ai")
    op.drop_column("flashcards", "hardness", schema="ai")
