"""flashcard reviews

Revision ID: flashcards_0002
Revises: flashcards_0001
Create Date: 2026-10-08 10:12:41.208113

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "flashcards_0002"
down_revision: str | Sequence[str] | None = "flashcards_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "flashcard_reviews",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("set_id", sa.Uuid(), nullable=False),
        sa.Column("card_id", sa.Uuid(), nullable=True),
        sa.Column(
            "rating",
            sa.Enum(
                "again",
                "hard",
                "medium",
                "easy",
                name="rating",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "state_before",
            sa.Enum(
                "new",
                "learning",
                "review",
                "relearning",
                name="state_before",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("interval_after_days", sa.REAL(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["card_id"],
            ["ai.flashcards.id"],
            name=op.f("fk_flashcard_reviews_card_id_flashcards"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["set_id"],
            ["ai.flashcard_sets.id"],
            name=op.f("fk_flashcard_reviews_set_id_flashcard_sets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flashcard_reviews")),
        schema="ai",
    )
    op.create_index(
        "ix_flashcard_reviews_set_id_reviewed_at",
        "flashcard_reviews",
        ["set_id", "reviewed_at"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "ix_flashcard_reviews_user_id_reviewed_at",
        "flashcard_reviews",
        ["user_id", "reviewed_at"],
        unique=False,
        schema="ai",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_flashcard_reviews_user_id_reviewed_at",
        table_name="flashcard_reviews",
        schema="ai",
    )
    op.drop_index(
        "ix_flashcard_reviews_set_id_reviewed_at",
        table_name="flashcard_reviews",
        schema="ai",
    )
    op.drop_table("flashcard_reviews", schema="ai")
