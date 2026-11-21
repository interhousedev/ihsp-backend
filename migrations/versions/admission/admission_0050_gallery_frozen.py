"""admission essay gallery: title, prompt and targets frozen at publish.

Revision ID: admission_0050_gallery_frozen
Revises: admission_0049_essay_flow
Create Date: 2026-11-21 21:00:00.000000

Entries published before this revision keep NULL and are served from the live essay.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "admission_0050_gallery_frozen"
down_revision: str | Sequence[str] | None = "admission_0049_essay_flow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
T = "essay_gallery"


def upgrade() -> None:
    """Add the frozen card columns."""
    op.add_column(T, sa.Column("title", sa.Text(), nullable=True), schema=S)
    op.add_column(T, sa.Column("prompt_text", sa.Text(), nullable=True), schema=S)
    op.add_column(T, sa.Column("word_limit", sa.Integer(), nullable=True), schema=S)
    op.add_column(
        T,
        sa.Column(
            "targets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        schema=S,
    )


def downgrade() -> None:
    """Drop the frozen card columns."""
    for c in ("targets", "word_limit", "prompt_text", "title"):
        op.drop_column(T, c, schema=S)
