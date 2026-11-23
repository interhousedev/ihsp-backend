"""admission: library books attached to a student's courses by staff.

Revision ID: admission_0067_attached_books
Revises: admission_0066_today_extras
Create Date: 2026-11-23 08:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0067_attached_books"
down_revision: str | Sequence[str] | None = "admission_0066_today_extras"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create `attached_books`."""
    NN: dict[str, bool] = {"nullable": False}  # noqa: N806
    op.create_table(
        "attached_books",
        sa.Column("id", sa.Uuid(), **NN),
        sa.Column("student_id", sa.Uuid(), **NN),
        sa.Column("item_id", sa.Uuid(), **NN),
        sa.Column("attached_by", sa.Uuid(), **NN),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.CheckConstraint(
            "char_length(note) <= 300",
            name=op.f("ck_attached_books_note_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attached_books")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_attached_books_student_id"),
        "attached_books",
        ["student_id"],
        schema=S,
    )
    op.create_index(
        "uq_attached_books_student_item",
        "attached_books",
        ["student_id", "item_id"],
        unique=True,
        schema=S,
    )


def downgrade() -> None:
    """Drop the table."""
    op.drop_table("attached_books", schema=S)
