"""Homework submissions: files a student hands in for a lesson's homework.

Revision ID: academic_0013
Revises: academic_0012
Create Date: 2026-11-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "academic_0013"
down_revision: str | Sequence[str] | None = "academic_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")


def upgrade() -> None:
    """Create academic.homework_submissions."""
    op.create_table(
        "homework_submissions",
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("file_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=NOW,
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.CheckConstraint(
            "cardinality(file_ids) BETWEEN 1 AND 10",
            name=op.f("ck_homework_submissions_file_count"),
        ),
        sa.CheckConstraint(
            "char_length(comment) <= 2000",
            name=op.f("ck_homework_submissions_comment_length"),
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["academic.lessons.id"],
            name=op.f("fk_homework_submissions_lesson_id_lessons"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["academic.students.user_id"],
            name=op.f("fk_homework_submissions_student_id_students"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_homework_submissions")),
        sa.UniqueConstraint(
            "lesson_id",
            "student_id",
            name="uq_homework_submissions_lesson_student",
        ),
        schema="academic",
    )
    op.create_index(
        "ix_homework_submissions_lesson_id",
        "homework_submissions",
        ["lesson_id"],
        unique=False,
        schema="academic",
    )


def downgrade() -> None:
    """Drop academic.homework_submissions."""
    op.drop_index(
        "ix_homework_submissions_lesson_id",
        table_name="homework_submissions",
        schema="academic",
    )
    op.drop_table("homework_submissions", schema="academic")
