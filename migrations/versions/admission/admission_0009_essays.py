"""admission essays: kind, title, notes, plan, links, version sharing and ideas.

Revision ID: admission_0009
Revises: admission_0006
Create Date: 2026-11-20 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0009"
down_revision: str | Sequence[str] | None = "admission_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = "kind IN ('personal_statement', 'supplemental', 'other')"
_SOURCES = "source IN ('interval', 'explicit', 'restore')"


def upgrade() -> None:
    """Add the drafting columns and the ideas board."""
    op.add_column(
        "essays",
        sa.Column(
            "kind",
            sa.String(length=20),
            server_default="personal_statement",
            nullable=False,
        ),
        schema="admission",
    )
    op.add_column(
        "essays",
        sa.Column("title", sa.String(length=120), server_default="", nullable=False),
        schema="admission",
    )
    op.add_column(
        "essays",
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        schema="admission",
    )
    for name in ("plan", "links"):
        op.add_column(
            "essays",
            sa.Column(
                name,
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'"),
                nullable=False,
            ),
            schema="admission",
        )
    op.add_column(
        "essays",
        sa.Column("last_snapshot_at", sa.DateTime(timezone=True), nullable=True),
        schema="admission",
    )
    op.create_check_constraint(
        op.f("ck_essays_kind"), "essays", _KINDS, schema="admission"
    )
    op.add_column(
        "essay_versions",
        sa.Column(
            "source", sa.String(length=10), server_default="explicit", nullable=False
        ),
        schema="admission",
    )
    op.add_column(
        "essay_versions",
        sa.Column(
            "shared", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        schema="admission",
    )
    op.add_column(
        "essay_versions",
        sa.Column("word_count", sa.Integer(), server_default="0", nullable=False),
        schema="admission",
    )
    op.create_check_constraint(
        op.f("ck_essay_versions_source"), "essay_versions", _SOURCES, schema="admission"
    )
    op.create_table(
        "essay_ideas",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("essay_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "tags", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "status", sa.String(length=8), server_default="explore", nullable=False
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lock_version", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "status IN ('explore', 'keep', 'drop')",
            name=op.f("ck_essay_ideas_status"),
        ),
        sa.CheckConstraint(
            "char_length(body) <= 1000", name=op.f("ck_essay_ideas_body_length")
        ),
        sa.ForeignKeyConstraint(
            ["essay_id"],
            ["admission.essays.id"],
            name=op.f("fk_essay_ideas_essay_id_essays"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_essay_ideas")),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_essay_ideas_student_id"),
        "essay_ideas",
        ["student_id"],
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_essay_ideas_essay_id"),
        "essay_ideas",
        ["essay_id"],
        schema="admission",
    )


def downgrade() -> None:
    """Drop the ideas board and the drafting columns."""
    op.drop_table("essay_ideas", schema="admission")
    op.drop_constraint(
        op.f("ck_essay_versions_source"), "essay_versions", schema="admission"
    )
    for name in ("word_count", "shared", "source"):
        op.drop_column("essay_versions", name, schema="admission")
    op.drop_constraint(op.f("ck_essays_kind"), "essays", schema="admission")
    for name in ("last_snapshot_at", "links", "plan", "notes", "title", "kind"):
        op.drop_column("essays", name, schema="admission")
