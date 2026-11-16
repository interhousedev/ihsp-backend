"""admission opportunities: taxonomy, catalog, moderated submissions and plans.

Revision ID: admission_0011
Revises: admission_0006
Create Date: 2026-11-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0011"
down_revision: str | Sequence[str] | None = "admission_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def _created() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _updated() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _lock() -> sa.Column:
    return sa.Column("lock_version", sa.Integer(), server_default="0", nullable=False)


def _json(name: str, default: str | None = None) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(default) if default else None,
        nullable=False,
    )


def upgrade() -> None:
    """Create the opportunities tables."""
    op.create_table(
        "opportunity_taxonomy",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        _json("names"),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        _created(),
        sa.CheckConstraint(
            "level IN ('field', 'subfield', 'subject')",
            name=op.f("ck_opportunity_taxonomy_level"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["admission.opportunity_taxonomy.id"],
            name=op.f("fk_opportunity_taxonomy_parent_id_opportunity_taxonomy"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunity_taxonomy")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_opportunity_taxonomy_parent_id"),
        "opportunity_taxonomy",
        ["parent_id"],
        schema=S,
    )
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=14), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        _json("payload"),
        _json("subject_ids", "'[]'::jsonb"),
        sa.Column("archived", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        _created(),
        _updated(),
        _lock(),
        sa.CheckConstraint(
            "kind IN ('exam', 'certification', 'course', 'event', 'recurring')",
            name=op.f("ck_opportunities_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunities")),
        schema=S,
    )
    op.create_table(
        "opportunity_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        _json("payload"),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column(
            "status", sa.String(length=10), server_default="pending", nullable=False
        ),
        sa.Column("submitted_by", sa.Uuid(), nullable=False),
        sa.Column("submitter_role", sa.String(length=10), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("applied_id", sa.Uuid(), nullable=True),
        _created(),
        _updated(),
        _lock(),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_opportunity_submissions_status"),
        ),
        sa.CheckConstraint(
            "submitter_role IN ('student', 'staff', 'helper', 'admin')",
            name=op.f("ck_opportunity_submissions_submitter_role"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunity_submissions")),
        schema=S,
    )
    op.create_index(
        "ix_opportunity_submissions_status",
        "opportunity_submissions",
        ["status", "created_at"],
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_opportunity_submissions_submitted_by"),
        "opportunity_submissions",
        ["submitted_by"],
        schema=S,
    )
    op.create_table(
        "opportunity_plan_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("planned_grade", sa.SmallInteger(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        _created(),
        sa.CheckConstraint(
            "planned_grade BETWEEN 9 AND 12",
            name=op.f("ck_opportunity_plan_entries_planned_grade"),
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["admission.opportunities.id"],
            name=op.f("fk_opportunity_plan_entries_opportunity_id_opportunities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunity_plan_entries")),
        sa.UniqueConstraint(
            "student_id",
            "opportunity_id",
            name=op.f("uq_opportunity_plan_entries_student_id"),
        ),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_opportunity_plan_entries_student_id"),
        "opportunity_plan_entries",
        ["student_id"],
        schema=S,
    )
    op.create_table(
        "opportunity_ai_plans",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        _json("plan"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_opportunity_ai_plans")),
        schema=S,
    )


def downgrade() -> None:
    """Drop the opportunities tables."""
    for table in (
        "opportunity_ai_plans",
        "opportunity_plan_entries",
        "opportunity_submissions",
        "opportunities",
        "opportunity_taxonomy",
    ):
        op.drop_table(table, schema=S)
