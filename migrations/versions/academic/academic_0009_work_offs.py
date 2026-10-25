"""Work-off templates and work-off tasks of absent students.

Revision ID: academic_0009
Revises: academic_0008
Create Date: 2026-10-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0009"
down_revision: str | Sequence[str] | None = "academic_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamps() -> list[sa.Column[object]]:
    return [
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
    ]


def upgrade() -> None:
    """Create the two tables."""
    op.create_table(
        "work_off_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        *_stamps(),
        sa.CheckConstraint(
            "char_length(text) BETWEEN 1 AND 1000",
            name=op.f("ck_work_off_templates_text_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_off_templates")),
        schema="academic",
    )
    op.create_index(
        "ix_work_off_templates_teacher_id",
        "work_off_templates",
        ["teacher_id"],
        schema="academic",
    )
    op.create_table(
        "work_offs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="assigned", nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        *_stamps(),
        sa.CheckConstraint(
            "status IN ('assigned', 'done')", name=op.f("ck_work_offs_status")
        ),
        sa.CheckConstraint(
            "char_length(text) BETWEEN 1 AND 2000",
            name=op.f("ck_work_offs_text_length"),
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["academic.lessons.id"],
            name=op.f("fk_work_offs_lesson_id_lessons"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["academic.students.user_id"],
            name=op.f("fk_work_offs_student_id_students"),
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["academic.work_off_templates.id"],
            name=op.f("fk_work_offs_template_id_work_off_templates"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_offs")),
        sa.UniqueConstraint(
            "lesson_id", "student_id", name="uq_work_offs_lesson_id_student_id"
        ),
        schema="academic",
    )
    op.create_index(
        "ix_work_offs_student_id_status",
        "work_offs",
        ["student_id", "status"],
        schema="academic",
    )


def downgrade() -> None:
    """Drop the two tables."""
    op.drop_index(
        "ix_work_offs_student_id_status", table_name="work_offs", schema="academic"
    )
    op.drop_table("work_offs", schema="academic")
    op.drop_index(
        "ix_work_off_templates_teacher_id",
        table_name="work_off_templates",
        schema="academic",
    )
    op.drop_table("work_off_templates", schema="academic")
