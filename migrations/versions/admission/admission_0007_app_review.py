"""admission app reviews: versioned AI reviews of the whole application.

Revision ID: admission_0007
Revises: admission_0006
Create Date: 2026-11-20 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0007"
down_revision: str | Sequence[str] | None = "admission_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create admission.app_reviews."""
    op.create_table(
        "app_reviews",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=8), server_default="queued", nullable=False
        ),
        sa.Column("locale", sa.String(length=5), nullable=False),
        sa.Column(
            "staff_visible",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "sections",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "models",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('queued', 'running', 'done', 'failed')",
            name=op.f("ck_app_reviews_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_reviews")),
        sa.UniqueConstraint("student_id", "version", name="uq_app_reviews_version"),
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_app_reviews_student_id"),
        "app_reviews",
        ["student_id"],
        unique=False,
        schema="admission",
    )


def downgrade() -> None:
    """Drop admission.app_reviews."""
    op.drop_index(
        op.f("ix_admission_app_reviews_student_id"),
        table_name="app_reviews",
        schema="admission",
    )
    op.drop_table("app_reviews", schema="admission")
