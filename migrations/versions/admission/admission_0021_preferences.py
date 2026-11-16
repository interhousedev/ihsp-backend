"""admission preferences and university swipe decisions.

Revision ID: admission_0021_preferences
Revises: admission_0020_doc_priority
Create Date: 2026-11-26 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0021_preferences"
down_revision: str | Sequence[str] | None = "admission_0020_doc_priority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create the two tables."""
    op.create_table(
        "student_preferences",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_student_preferences")),
        schema=S,
    )
    op.create_table(
        "university_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=12), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_list_entry",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
            "decision IN ('interested', 'not_my_vibe')",
            name=op.f("ck_university_decisions_decision"),
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_university_decisions_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_university_decisions")),
        sa.UniqueConstraint(
            "student_id",
            "institution_id",
            name=op.f("uq_university_decisions_student_institution"),
        ),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_university_decisions_student_id"),
        "university_decisions",
        ["student_id"],
        schema=S,
    )


def downgrade() -> None:
    """Drop the tables."""
    op.drop_table("university_decisions", schema=S)
    op.drop_table("student_preferences", schema=S)
