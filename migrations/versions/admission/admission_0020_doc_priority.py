"""admission checklist priority: student importance, urgency override.

Revision ID: admission_0020_doc_priority
Revises: admission_0019_timestamps
Create Date: 2026-11-25 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0020_doc_priority"
down_revision: str | Sequence[str] | None = "admission_0019_timestamps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Add importance and the urgency override."""
    op.add_column(
        "checklist_items",
        sa.Column(
            "important", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        schema=S,
    )
    op.add_column(
        "checklist_items",
        sa.Column("urgent_override", sa.Boolean(), nullable=True),
        schema=S,
    )


def downgrade() -> None:
    """Drop the columns."""
    op.drop_column("checklist_items", "urgent_override", schema=S)
    op.drop_column("checklist_items", "important", schema=S)
