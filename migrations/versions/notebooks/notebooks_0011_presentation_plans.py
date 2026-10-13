"""Presentation plans: slide outlines confirmed before a deck is generated (PLAN).

Revision ID: notebooks_0011
Revises: notebooks_0010
Create Date: 2026-10-14 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "notebooks_0011"
down_revision: str | Sequence[str] | None = "notebooks_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create notebooks.presentation_plans."""
    op.create_table(
        "presentation_plans",
        sa.Column("notebook_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slides", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "confirmed",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column(
            "source_ids",
            sa.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "format",
            sa.String(length=16),
            server_default=sa.text("'presenter'"),
            nullable=False,
        ),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["notebook_id"],
            ["notebooks.notebooks.id"],
            name=op.f("fk_presentation_plans_notebook_id_notebooks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["notebooks.artifacts.id"],
            name=op.f("fk_presentation_plans_artifact_id_artifacts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_presentation_plans")),
        schema="notebooks",
    )
    op.create_index(
        "ix_presentation_plans_notebook_id_owner_id",
        "presentation_plans",
        ["notebook_id", "owner_id"],
        unique=False,
        schema="notebooks",
    )


def downgrade() -> None:
    """Drop notebooks.presentation_plans."""
    op.drop_index(
        "ix_presentation_plans_notebook_id_owner_id",
        table_name="presentation_plans",
        schema="notebooks",
    )
    op.drop_table("presentation_plans", schema="notebooks")
