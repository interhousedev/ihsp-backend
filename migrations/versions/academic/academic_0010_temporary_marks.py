"""Temporary gradebook: marks kept on the platform until they are in EMIS.

Revision ID: academic_0010
Revises: academic_0009
Create Date: 2026-10-20 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0010"
down_revision: str | Sequence[str] | None = "academic_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_temporary_marks_student_id_subject_id_date"


def upgrade() -> None:
    """Create ``academic.temporary_marks``."""
    op.create_table(
        "temporary_marks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("author_id", sa.Uuid(), nullable=False),
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
            "value BETWEEN 2 AND 5", name=op.f("ck_temporary_marks_value")
        ),
        sa.CheckConstraint(
            "comment IS NULL OR char_length(comment) BETWEEN 1 AND 500",
            name=op.f("ck_temporary_marks_comment_length"),
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["academic.lessons.id"],
            name=op.f("fk_temporary_marks_lesson_id_lessons"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["academic.students.user_id"],
            name=op.f("fk_temporary_marks_student_id_students"),
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["academic.subjects.id"],
            name=op.f("fk_temporary_marks_subject_id_subjects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_temporary_marks")),
        sa.UniqueConstraint(
            "lesson_id", "student_id", name="uq_temporary_marks_lesson_id_student_id"
        ),
        schema="academic",
    )
    op.create_index(
        INDEX,
        "temporary_marks",
        ["student_id", "subject_id", "date"],
        schema="academic",
    )


def downgrade() -> None:
    """Drop ``academic.temporary_marks``."""
    op.drop_index(INDEX, table_name="temporary_marks", schema="academic")
    op.drop_table("temporary_marks", schema="academic")
