"""admission: stored prompt-group labels and the idea fit cache.

Revision ID: admission_0054_essay_ledger
Revises: admission_0053_fit_professions
Create Date: 2026-11-21 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0054_essay_ledger"
down_revision: str | Sequence[str] | None = "admission_0053_fit_professions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def _created() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    """Create prompt_group_labels and idea_fits."""
    op.create_table(
        "prompt_group_labels",
        sa.Column("members_hash", sa.String(length=64), nullable=False),
        sa.Column("label_ru", sa.String(length=80), nullable=False),
        sa.Column("label_en", sa.String(length=80), nullable=False),
        sa.Column("label_uz", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=200), server_default="", nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("members_hash", name=op.f("pk_prompt_group_labels")),
        schema=S,
    )
    op.create_table(
        "idea_fits",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("text_digest", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("student_id", "text_digest", name=op.f("pk_idea_fits")),
        schema=S,
    )


def downgrade() -> None:
    """Drop both tables."""
    op.drop_table("idea_fits", schema=S)
    op.drop_table("prompt_group_labels", schema=S)
