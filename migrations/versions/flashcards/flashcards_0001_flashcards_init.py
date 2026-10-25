"""flashcards init

Revision ID: flashcards_0001
Revises:
Create Date: 2026-10-07 17:01:04.470715

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "flashcards_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("flashcards",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Schema ai is shared with the ai branch, which may be upgraded first.
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")
    op.create_table(
        "flashcard_sets",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "manual",
                "ai",
                "mcp",
                "copied",
                name="source",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_chat_id", sa.Uuid(), nullable=True),
        sa.Column("copied_from_set_id", sa.Uuid(), nullable=True),
        sa.Column(
            "new_per_day",
            sa.SmallInteger(),
            server_default=sa.text("20"),
            nullable=False,
        ),
        sa.Column(
            "reviews_per_day",
            sa.SmallInteger(),
            server_default=sa.text("200"),
            nullable=False,
        ),
        sa.Column(
            "card_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
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
            ["copied_from_set_id"],
            ["ai.flashcard_sets.id"],
            name=op.f("fk_flashcard_sets_copied_from_set_id_flashcard_sets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flashcard_sets")),
        schema="ai",
    )
    op.create_index(
        "ix_flashcard_sets_owner_id",
        "flashcard_sets",
        ["owner_id"],
        unique=False,
        schema="ai",
    )
    op.create_table(
        "flashcards",
        sa.Column("set_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "new",
                "learning",
                "review",
                "relearning",
                name="state",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'new'"),
            nullable=False,
        ),
        sa.Column(
            "step", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "interval_days", sa.REAL(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("ease", sa.REAL(), server_default=sa.text("2.5"), nullable=False),
        sa.Column("reps", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lapses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
            ["set_id"],
            ["ai.flashcard_sets.id"],
            name=op.f("fk_flashcards_set_id_flashcard_sets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flashcards")),
        schema="ai",
    )
    op.create_index(
        "ix_flashcards_set_id_due_at",
        "flashcards",
        ["set_id", "due_at"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "ix_flashcards_set_id_position",
        "flashcards",
        ["set_id", "position"],
        unique=False,
        schema="ai",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_flashcards_set_id_position", table_name="flashcards", schema="ai")
    op.drop_index("ix_flashcards_set_id_due_at", table_name="flashcards", schema="ai")
    op.drop_table("flashcards", schema="ai")
    op.drop_index(
        "ix_flashcard_sets_owner_id", table_name="flashcard_sets", schema="ai"
    )
    op.drop_table("flashcard_sets", schema="ai")
    # Shared with the ai branch: this branch never drops tables or schema of ai;
    # the schema goes only when nothing is left in it.
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS "
        "(SELECT 1 FROM pg_tables WHERE schemaname = 'ai') "
        "THEN DROP SCHEMA IF EXISTS ai; END IF; END $$"
    )
