"""admission memory notes for the student's AI agent (MCP).

Revision ID: admission_0029_mcp
Revises: admission_0028_kb
Create Date: 2026-11-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0029_mcp"
down_revision: str | Sequence[str] | None = "admission_0028_kb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create the memory notes table."""
    op.create_table(
        "memory_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=9), nullable=False),
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
        sa.CheckConstraint(
            "source IN ('app', 'mcp', 'assistant')",
            name=op.f("ck_memory_notes_source"),
        ),
        sa.CheckConstraint(
            "char_length(content) <= 4000",
            name=op.f("ck_memory_notes_content_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_notes")),
        schema=S,
    )
    op.create_index(
        "ix_memory_notes_student_id_created_at",
        "memory_notes",
        ["student_id", "created_at"],
        schema=S,
    )


def downgrade() -> None:
    """Drop the memory notes table."""
    op.drop_index("ix_memory_notes_student_id_created_at", "memory_notes", schema=S)
    op.drop_table("memory_notes", schema=S)
