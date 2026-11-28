"""EMIS thematic plan topics per subject (the question bank's catalogue).

Revision ID: academic_0017
Revises: academic_0016
Create Date: 2026-11-27 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0017"
down_revision: str | Sequence[str] | None = "academic_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create academic.curriculum_topics."""
    op.create_table(
        "curriculum_topics",
        sa.Column("emis_subject_id", sa.Integer(), nullable=False),
        sa.Column("semester", sa.SmallInteger(), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "emis_subject_id", "semester", "topic", name="pk_curriculum_topics"
        ),
        schema="academic",
    )
    op.create_index(
        "ix_curriculum_topics_emis_subject_id",
        "curriculum_topics",
        ["emis_subject_id"],
        schema="academic",
    )


def downgrade() -> None:
    """Drop academic.curriculum_topics."""
    op.drop_index(
        "ix_curriculum_topics_emis_subject_id",
        table_name="curriculum_topics",
        schema="academic",
    )
    op.drop_table("curriculum_topics", schema="academic")
