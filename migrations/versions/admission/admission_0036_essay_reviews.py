"""admission essay_reviews: stored coach checks, base and university reviews.

Revision ID: admission_0036_essay_reviews
Revises: admission_0035_essay_sealed
Create Date: 2026-11-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0036_essay_reviews"
down_revision: str | Sequence[str] | None = "admission_0035_essay_sealed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create the sealed review store keyed by essay, kind, university and input."""
    op.create_table(
        "essay_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("essay_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=True),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("result", sa.LargeBinary(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("prompt_ref", sa.String(length=200), nullable=False),
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
        sa.CheckConstraint(
            "kind IN ('check', 'base', 'uni')", name=op.f("ck_essay_reviews_kind")
        ),
        sa.ForeignKeyConstraint(
            ["essay_id"],
            ["admission.essays.id"],
            name=op.f("fk_essay_reviews_essay_id_essays"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_essay_reviews_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_essay_reviews")),
        schema=S,
    )
    op.create_index(
        "uq_essay_reviews_input",
        "essay_reviews",
        ["essay_id", "kind", "institution_id", "input_digest"],
        unique=True,
        schema=S,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_essay_reviews_latest",
        "essay_reviews",
        ["essay_id", "kind", "created_at"],
        schema=S,
    )
    op.create_index(
        "ix_essay_reviews_student_id", "essay_reviews", ["student_id"], schema=S
    )


def downgrade() -> None:
    """Drop the review store (its indexes go with it)."""
    op.drop_table("essay_reviews", schema=S)
