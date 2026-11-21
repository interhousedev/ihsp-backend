"""admission: link an activity to an opportunity (pending submission or entry).

Revision ID: admission_0060_item_opportunity_link
Revises: admission_0059_item_text_limits
Create Date: 2026-11-22 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0060_item_opportunity_link"
down_revision: str | Sequence[str] | None = "admission_0059_item_text_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
T = "item_opportunity_links"


def upgrade() -> None:
    """Create `item_opportunity_links`."""
    op.create_table(
        T,
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["admission.items.id"],
            name=op.f("fk_item_opportunity_links_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["admission.opportunity_submissions.id"],
            name=op.f(
                "fk_item_opportunity_links_submission_id_opportunity_submissions"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["admission.opportunities.id"],
            name=op.f("fk_item_opportunity_links_opportunity_id_opportunities"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("item_id", name=op.f("pk_item_opportunity_links")),
        schema=S,
    )
    op.create_index(
        "ix_item_opportunity_links_submission_id", T, ["submission_id"], schema=S
    )
    op.create_index(
        "ix_item_opportunity_links_opportunity_id", T, ["opportunity_id"], schema=S
    )


def downgrade() -> None:
    """Drop `item_opportunity_links`."""
    op.drop_index("ix_item_opportunity_links_opportunity_id", T, schema=S)
    op.drop_index("ix_item_opportunity_links_submission_id", T, schema=S)
    op.drop_table(T, schema=S)
