"""admission essay flow: prompt targets, forks, daily practice, gallery, slots.

Revision ID: admission_0049_essay_flow
Revises: admission_0048_plan_grade_range
Create Date: 2026-11-21 19:00:00.000000

Essays get ``targets`` (the prompts a draft answers, a JSON list copied from the
catalog) and ``forked_from``. New tables: ``essay_practice`` (one sealed entry per
student per day), ``essay_gallery`` (a version a student published, anonymous) and
``essay_slots`` (an essay in a prompt slot of one university). The review kinds gain
``deep``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "admission_0049_essay_flow"
down_revision: str | Sequence[str] | None = "admission_0048_plan_grade_range"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
KIND_CK = "ck_essay_reviews_kind"


def _stamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
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
    ]


def upgrade() -> None:
    """Add the essay columns and the three flow tables; allow the deep review."""
    op.add_column(
        "essays",
        sa.Column(
            "targets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        schema=S,
    )
    op.add_column("essays", sa.Column("forked_from", sa.Uuid(), nullable=True), schema=S)
    op.create_foreign_key(
        op.f("fk_essays_forked_from_essays"),
        "essays",
        "essays",
        ["forked_from"],
        ["id"],
        source_schema=S,
        referent_schema=S,
        ondelete="SET NULL",
    )
    op.drop_constraint(op.f(KIND_CK), "essay_reviews", schema=S, type_="check")
    op.create_check_constraint(
        op.f(KIND_CK),
        "essay_reviews",
        "kind IN ('check', 'base', 'uni', 'deep')",
        schema=S,
    )

    op.create_table(
        "essay_practice",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("theme", sa.String(length=40), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("evaluation", sa.LargeBinary(), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        *_stamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_essay_practice")),
        sa.UniqueConstraint(
            "student_id", "day", name=op.f("uq_essay_practice_student_id")
        ),
        schema=S,
    )
    op.create_index(
        "ix_essay_practice_student_id", "essay_practice", ["student_id"], schema=S
    )

    op.create_table(
        "essay_gallery",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("essay_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["essay_id"],
            ["admission.essays.id"],
            name=op.f("fk_essay_gallery_essay_id_essays"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_essay_gallery")),
        sa.UniqueConstraint("essay_id", name=op.f("uq_essay_gallery_essay_id")),
        schema=S,
    )
    op.create_index(
        "ix_essay_gallery_student_id", "essay_gallery", ["student_id"], schema=S
    )

    op.create_table(
        "essay_slots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("slot", sa.String(length=10), nullable=False),
        sa.Column("essay_id", sa.Uuid(), nullable=False),
        *_stamps(),
        sa.CheckConstraint(
            "slot ~ '^(ps|supp:[0-9]{1,3})$'", name=op.f("ck_essay_slots_slot_format")
        ),
        sa.ForeignKeyConstraint(
            ["essay_id"],
            ["admission.essays.id"],
            name=op.f("fk_essay_slots_essay_id_essays"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_essay_slots_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_essay_slots")),
        sa.UniqueConstraint(
            "student_id", "institution_id", "slot", name="uq_essay_slots_slot"
        ),
        sa.UniqueConstraint(
            "student_id", "institution_id", "essay_id", name="uq_essay_slots_essay"
        ),
        schema=S,
    )
    op.create_index(
        "ix_essay_slots_student_id", "essay_slots", ["student_id"], schema=S
    )


def downgrade() -> None:
    """Drop the flow tables and columns (deep reviews are deleted)."""
    op.drop_table("essay_slots", schema=S)
    op.drop_table("essay_gallery", schema=S)
    op.drop_table("essay_practice", schema=S)
    op.execute("DELETE FROM admission.essay_reviews WHERE kind = 'deep'")
    op.drop_constraint(op.f(KIND_CK), "essay_reviews", schema=S, type_="check")
    op.create_check_constraint(
        op.f(KIND_CK), "essay_reviews", "kind IN ('check', 'base', 'uni')", schema=S
    )
    op.drop_constraint(
        op.f("fk_essays_forked_from_essays"), "essays", schema=S, type_="foreignkey"
    )
    op.drop_column("essays", "forked_from", schema=S)
    op.drop_column("essays", "targets", schema=S)
