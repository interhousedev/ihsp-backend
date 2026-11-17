"""admission opportunities.created_by nullable, cleared when its author is erased.

Revision ID: admission_0034_opp_author_null
Revises: admission_0033_supp_prompts
Create Date: 2026-11-18 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0034_opp_author_null"
down_revision: str | Sequence[str] | None = "admission_0033_supp_prompts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Allow an entry without a known author."""
    op.alter_column(
        "opportunities", "created_by", existing_type=sa.Uuid(), nullable=True, schema=S
    )


def downgrade() -> None:
    """Require the author again (rows of erased authors must be fixed first)."""
    op.alter_column(
        "opportunities", "created_by", existing_type=sa.Uuid(), nullable=False, schema=S
    )
