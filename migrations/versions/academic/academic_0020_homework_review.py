"""Homework linked to EMIS and reviewed by the teacher.

Lessons get the EMIS homework file, the EMIS topic description, a per-lesson switch
for submissions and a per-lesson notification override. Submissions get a text,
optional files and a review (status, grade, teacher comment). Teachers get
``academic.teacher_homework_settings``.

Revision ID: academic_0020
Revises: academic_0019
Create Date: 2026-11-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0020"
down_revision: str | Sequence[str] | None = "academic_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")
TABLE = "homework_submissions"


def _check(name: str, expression: str) -> None:
    op.create_check_constraint(
        op.f(f"ck_{TABLE}_{name}"), TABLE, expression, schema="academic"
    )


def upgrade() -> None:
    """Add the lesson, submission and settings columns."""
    op.add_column(
        "lessons",
        sa.Column("emis_homework_url", sa.Text(), nullable=True),
        schema="academic",
    )
    op.add_column(
        "lessons",
        sa.Column("emis_topic_description", sa.Text(), nullable=True),
        schema="academic",
    )
    op.add_column(
        "lessons",
        sa.Column(
            "homework_accept_submissions",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema="academic",
    )
    op.add_column(
        "lessons",
        sa.Column("homework_notify", sa.Boolean(), nullable=True),
        schema="academic",
    )
    # Every lesson with homework text accepts submissions today: keep it so.
    op.execute(
        "UPDATE academic.lessons SET homework_accept_submissions = true "
        "WHERE homework_text IS NOT NULL"
    )

    op.add_column(TABLE, sa.Column("text", sa.Text(), nullable=True), schema="academic")
    op.drop_constraint(
        op.f(f"ck_{TABLE}_file_count"), TABLE, type_="check", schema="academic"
    )
    _check("file_count", "cardinality(file_ids) <= 10")
    _check("content", "cardinality(file_ids) >= 1 OR text IS NOT NULL")
    _check("text_length", "char_length(text) <= 10000")
    op.add_column(
        TABLE,
        sa.Column(
            "review_status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        schema="academic",
    )
    op.add_column(
        TABLE, sa.Column("grade", sa.SmallInteger(), nullable=True), schema="academic"
    )
    op.add_column(
        TABLE, sa.Column("teacher_comment", sa.Text(), nullable=True), schema="academic"
    )
    op.add_column(
        TABLE,
        sa.Column("previous_comment", sa.Text(), nullable=True),
        schema="academic",
    )
    op.add_column(
        TABLE, sa.Column("reviewed_by", sa.Uuid(), nullable=True), schema="academic"
    )
    op.add_column(
        TABLE,
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        schema="academic",
    )
    op.add_column(
        TABLE,
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        schema="academic",
    )
    op.add_column(
        TABLE,
        sa.Column("temporary_mark_id", sa.Uuid(), nullable=True),
        schema="academic",
    )
    op.create_foreign_key(
        op.f("fk_homework_submissions_temporary_mark_id_temporary_marks"),
        TABLE,
        "temporary_marks",
        ["temporary_mark_id"],
        ["id"],
        source_schema="academic",
        referent_schema="academic",
        ondelete="SET NULL",
    )
    _check("review_status", "review_status IN ('pending', 'returned', 'graded')")
    _check("grade_range", "grade BETWEEN 2 AND 5")
    _check("graded_has_grade", "review_status <> 'graded' OR grade IS NOT NULL")
    _check("teacher_comment_length", "char_length(teacher_comment) <= 2000")
    op.create_index(
        "ix_homework_submissions_review",
        TABLE,
        ["lesson_id", "review_status"],
        unique=False,
        schema="academic",
    )

    op.create_table(
        "teacher_homework_settings",
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column(
            "accept_by_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "notify_on_submission",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False
        ),
        sa.PrimaryKeyConstraint(
            "teacher_id", name=op.f("pk_teacher_homework_settings")
        ),
        schema="academic",
    )


def downgrade() -> None:
    """Drop what the upgrade added."""
    op.drop_table("teacher_homework_settings", schema="academic")
    op.drop_index("ix_homework_submissions_review", table_name=TABLE, schema="academic")
    for name in (
        "teacher_comment_length",
        "graded_has_grade",
        "grade_range",
        "review_status",
        "text_length",
        "content",
        "file_count",
    ):
        op.drop_constraint(
            op.f(f"ck_{TABLE}_{name}"), TABLE, type_="check", schema="academic"
        )
    op.drop_constraint(
        op.f("fk_homework_submissions_temporary_mark_id_temporary_marks"),
        TABLE,
        type_="foreignkey",
        schema="academic",
    )
    for column in (
        "temporary_mark_id",
        "notified_at",
        "reviewed_at",
        "reviewed_by",
        "previous_comment",
        "teacher_comment",
        "grade",
        "review_status",
        "text",
    ):
        op.drop_column(TABLE, column, schema="academic")
    _check("file_count", "cardinality(file_ids) BETWEEN 1 AND 10")
    for column in (
        "homework_notify",
        "homework_accept_submissions",
        "emis_topic_description",
        "emis_homework_url",
    ):
        op.drop_column("lessons", column, schema="academic")
