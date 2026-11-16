"""admission catalog: staff proposals to add or edit institutions and scholarships.

Revision ID: admission_0004
Revises: admission_0003
Create Date: 2026-11-17 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0004"
down_revision: str | Sequence[str] | None = "admission_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the proposals table."""
    op.create_table(
        "catalog_proposals",
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column(
            "status", sa.String(length=10), server_default="pending", nullable=False
        ),
        sa.Column("proposed_by", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("applied_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lock_version", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "kind IN ('institution', 'scholarship')",
            name=op.f("ck_catalog_proposals_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_catalog_proposals_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_proposals")),
        schema="admission",
    )
    op.create_index(
        "ix_catalog_proposals_status",
        "catalog_proposals",
        ["status", "created_at"],
        schema="admission",
    )
    op.create_index(
        op.f("ix_admission_catalog_proposals_proposed_by"),
        "catalog_proposals",
        ["proposed_by"],
        schema="admission",
    )


def downgrade() -> None:
    """Drop the proposals table."""
    op.drop_table("catalog_proposals", schema="admission")
