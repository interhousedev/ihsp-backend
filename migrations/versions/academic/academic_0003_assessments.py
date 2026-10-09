"""assessments (midterm and final controls), control weeks of a term, ACA-15 recompute

Revision ID: academic_0003
Revises: academic_0002
Create Date: 2026-10-08 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "academic_0003"
down_revision: str | Sequence[str] | None = "academic_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ACA-15 changed: a semester mark is the mean of the type means that have marks, not
# only the lesson mean until all three types exist. Stored results are recomputed from
# the marks (the sync would refresh them only when EMIS data changes).
RECOMPUTE_RESULTS = """
UPDATE academic.results AS r
SET value = fresh.value
FROM (
    SELECT student_id, subject_id, semester, ROUND(AVG(type_avg), 2) AS value
    FROM (
        SELECT student_id, subject_id, semester, type, AVG(value::numeric) AS type_avg
        FROM academic.marks
        WHERE removed_at IS NULL
        GROUP BY student_id, subject_id, semester, type
    ) AS per_type
    GROUP BY student_id, subject_id, semester
) AS fresh
WHERE r.subject_id IS NOT NULL
  AND r.student_id = fresh.student_id
  AND r.subject_id = fresh.subject_id
  AND r.semester = fresh.semester
"""


def upgrade() -> None:
    """Add terms.control_periods and the assessments table; recompute the results."""
    op.add_column(
        "terms",
        sa.Column(
            "control_periods",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema="academic",
    )
    op.create_table(
        "assessments",
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("audience", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "midterm",
                "final",
                "other",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("lesson_id", sa.Uuid(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("room", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "tentative",
                "cancelled",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "teacher",
                "admin",
                "emis",
                "head_student",
                name="source",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "control",
            sa.Enum(
                "midterm_1",
                "midterm_2",
                "final",
                name="control",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
            "cardinality(audience) > 0", name=op.f("ck_assessments_audience_not_empty")
        ),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["academic.lessons.id"],
            name=op.f("fk_assessments_lesson_id_lessons"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["academic.subjects.id"],
            name=op.f("fk_assessments_subject_id_subjects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessments")),
        schema="academic",
    )
    op.create_index(
        "ix_assessments_date", "assessments", ["date"], unique=False, schema="academic"
    )
    op.create_index(
        "ix_assessments_subject_id",
        "assessments",
        ["subject_id"],
        unique=False,
        schema="academic",
    )
    op.create_index(
        "ix_assessments_audience",
        "assessments",
        ["audience"],
        unique=False,
        schema="academic",
        postgresql_using="gin",
    )
    op.create_index(
        "uq_assessments_emis_lesson_id",
        "assessments",
        ["lesson_id"],
        unique=True,
        schema="academic",
        postgresql_where=sa.text("source = 'emis' AND lesson_id IS NOT NULL"),
    )
    op.execute(RECOMPUTE_RESULTS)


def downgrade() -> None:
    """Drop the assessments table and the control weeks.

    Semester marks stay as ACA-15 now computes them; the sync refreshes them.
    """
    op.drop_index(
        "uq_assessments_emis_lesson_id", table_name="assessments", schema="academic"
    )
    op.drop_index("ix_assessments_audience", table_name="assessments", schema="academic")
    op.drop_index(
        "ix_assessments_subject_id", table_name="assessments", schema="academic"
    )
    op.drop_index("ix_assessments_date", table_name="assessments", schema="academic")
    op.drop_table("assessments", schema="academic")
    op.drop_column("terms", "control_periods", schema="academic")
