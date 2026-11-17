"""admission self-reported application outcomes.

Revision ID: admission_0024_outcomes
Revises: admission_0023_catalog_facts
Create Date: 2026-11-27 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0024_outcomes"
down_revision: str | Sequence[str] | None = "admission_0023_catalog_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create the outcomes table."""
    op.create_table(
        "application_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("cycle", sa.Integer(), nullable=False),
        sa.Column("plan", sa.String(length=8), server_default="rd", nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default="applied", nullable=False
        ),
        sa.Column(
            "share_name", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
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
            "status IN ('applied', 'accepted', 'rejected', 'waitlisted', "
            "'deferred', 'enrolled')",
            name=op.f("ck_application_outcomes_status"),
        ),
        sa.CheckConstraint(
            "plan IN ('ed', 'ed2', 'ea', 'rea', 'rd', 'rolling', 'other')",
            name=op.f("ck_application_outcomes_plan"),
        ),
        sa.CheckConstraint(
            "cycle BETWEEN 2000 AND 2100",
            name=op.f("ck_application_outcomes_cycle_range"),
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_application_outcomes_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_outcomes")),
        sa.UniqueConstraint(
            "student_id",
            "institution_id",
            "cycle",
            name=op.f("uq_application_outcomes_student_institution_cycle"),
        ),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_application_outcomes_student_id"),
        "application_outcomes",
        ["student_id"],
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_application_outcomes_institution_id"),
        "application_outcomes",
        ["institution_id"],
        schema=S,
    )


def downgrade() -> None:
    """Drop the outcomes table."""
    op.drop_table("application_outcomes", schema=S)
