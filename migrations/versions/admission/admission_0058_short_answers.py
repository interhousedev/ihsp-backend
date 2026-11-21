"""admission: sealed short answers per supplemental prompt.

Revision ID: admission_0058_short_answers
Revises: admission_0057_updated_at
Create Date: 2026-11-22 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0058_short_answers"
down_revision: str | Sequence[str] | None = "admission_0057_updated_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create `essay_short_answers` (the text is sealed ciphertext)."""
    op.create_table(
        "essay_short_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_key", sa.String(length=80), nullable=False),
        sa.Column("text", sa.LargeBinary(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_essay_short_answers")),
        sa.UniqueConstraint(
            "student_id", "prompt_key", name="uq_essay_short_answers_key"
        ),
        schema=S,
    )
    op.create_index(
        "ix_essay_short_answers_student_id",
        "essay_short_answers",
        ["student_id"],
        schema=S,
    )


def downgrade() -> None:
    """Drop `essay_short_answers`."""
    op.drop_index("ix_essay_short_answers_student_id", "essay_short_answers", schema=S)
    op.drop_table("essay_short_answers", schema=S)
