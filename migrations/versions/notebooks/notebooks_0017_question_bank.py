"""The question bank per EMIS subject and topic.

Revision ID: notebooks_0017
Revises: notebooks_0016
Create Date: 2026-11-27 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "notebooks_0017"
down_revision: str | Sequence[str] | None = "notebooks_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create notebooks.question_bank."""
    op.create_table(
        "question_bank",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("emis_subject_id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.String(length=8), nullable=False),
        sa.Column("origin", sa.String(length=8), nullable=False),
        sa.Column("visibility", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "difficulty IN ('easy', 'medium', 'hard')",
            name=op.f("ck_question_bank_difficulty"),
        ),
        sa.CheckConstraint(
            "origin IN ('ai', 'teacher')", name=op.f("ck_question_bank_origin")
        ),
        sa.CheckConstraint(
            "visibility IN ('teacher', 'subject')",
            name=op.f("ck_question_bank_visibility"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_bank")),
        schema="notebooks",
    )
    op.create_index(
        "ix_question_bank_emis_subject_id_topic",
        "question_bank",
        ["emis_subject_id", "topic"],
        schema="notebooks",
    )
    op.create_index(
        "ix_question_bank_owner_id", "question_bank", ["owner_id"], schema="notebooks"
    )


def downgrade() -> None:
    """Drop notebooks.question_bank."""
    op.drop_table("question_bank", schema="notebooks")
