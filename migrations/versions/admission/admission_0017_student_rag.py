"""admission student data search: chunks with a words index.

Revision ID: admission_0017_student_rag
Revises: admission_0016_test_scores
Create Date: 2026-11-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0017_student_rag"
down_revision: str | Sequence[str] | None = "admission_0016_test_scores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    op.create_table(
        "admission_student_chunks",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("ref_id", sa.String(80), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', title || ' ' || body)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "student_id",
            "source",
            "ref_id",
            "seq",
            name=op.f("pk_admission_student_chunks"),
        ),
        schema=S,
    )
    op.create_index(
        "ix_admission_student_chunks_tsv",
        "admission_student_chunks",
        ["tsv"],
        schema=S,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admission_student_chunks_tsv",
        table_name="admission_student_chunks",
        schema=S,
    )
    op.drop_table("admission_student_chunks", schema=S)
