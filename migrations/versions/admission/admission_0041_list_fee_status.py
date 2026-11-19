"""admission list entry application-fee status.

Revision ID: admission_0041_list_fee_status
Revises: admission_0040_opp_research
Create Date: 2026-11-23 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql.elements import conv

# revision identifiers, used by Alembic.
revision: str = "admission_0041_list_fee_status"
down_revision: str | Sequence[str] | None = "admission_0040_opp_research"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
NAME = conv("ck_list_entries_fee_status")
CONDITION = "fee_status IN ('unpaid', 'paid', 'waiver_requested', 'waiver_approved')"


def upgrade() -> None:
    """Add the fee status column with its check."""
    op.add_column(
        "list_entries",
        sa.Column("fee_status", sa.Text(), server_default="unpaid", nullable=False),
        schema=S,
    )
    op.create_check_constraint(NAME, "list_entries", CONDITION, schema=S)


def downgrade() -> None:
    """Drop the fee status column."""
    op.drop_constraint(NAME, "list_entries", schema=S, type_="check")
    op.drop_column("list_entries", "fee_status", schema=S)
