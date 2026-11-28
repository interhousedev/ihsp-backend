"""admission: personal plan entries, a student's own finds outside the catalog.

Revision ID: admission_0071_personal_plan
Revises: admission_0070_opp_audience
Create Date: 2026-11-28 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0071_personal_plan"
down_revision: str | Sequence[str] | None = "admission_0070_opp_audience"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
T = "opportunity_personal_entries"
KINDS = (
    "exam",
    "certification",
    "course",
    "event",
    "recurring",
    "program",
    "scholarship",
    "research",
)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    """Create `opportunity_personal_entries`."""
    op.create_table(
        T,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=300), nullable=True),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("summary", sa.String(length=2000), nullable=True),
        sa.Column("registration_deadline", sa.Date(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("planned_grade", sa.SmallInteger(), nullable=True),
        sa.Column("planned_term", sa.String(length=8), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("origin", sa.String(length=8), nullable=False),
        sa.Column("dedup_key", sa.String(length=64), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lock_version", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(_in("kind", KINDS), name=op.f(f"ck_{T}_kind")),
        sa.CheckConstraint(_in("origin", ("web", "mcp")), name=op.f(f"ck_{T}_origin")),
        sa.CheckConstraint(
            "planned_grade BETWEEN 1 AND 12", name=op.f(f"ck_{T}_planned_grade")
        ),
        sa.CheckConstraint(
            "planned_term IN ('fall', 'spring', 'summer')",
            name=op.f(f"ck_{T}_planned_term"),
        ),
        sa.CheckConstraint("ends_on >= starts_on", name=op.f(f"ck_{T}_dates")),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["admission.opportunity_submissions.id"],
            name="fk_opp_personal_entries_submission_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{T}")),
        sa.UniqueConstraint("student_id", "dedup_key", name=op.f(f"uq_{T}_student_id")),
        schema=S,
    )
    op.create_index(op.f(f"ix_admission_{T}_student_id"), T, ["student_id"], schema=S)
    op.create_index(
        op.f(f"ix_admission_{T}_submission_id"), T, ["submission_id"], schema=S
    )


def downgrade() -> None:
    """Drop `opportunity_personal_entries`."""
    op.drop_index(op.f(f"ix_admission_{T}_submission_id"), T, schema=S)
    op.drop_index(op.f(f"ix_admission_{T}_student_id"), T, schema=S)
    op.drop_table(T, schema=S)
