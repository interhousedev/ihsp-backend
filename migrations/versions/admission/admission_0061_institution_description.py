"""admission: localized description of an institution.

Revision ID: admission_0061_institution_description
Revises: admission_0060_item_opportunity_link
Create Date: 2026-11-22 03:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "admission_0061_institution_description"
down_revision: str | Sequence[str] | None = "admission_0060_item_opportunity_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
T = "institutions"


def upgrade() -> None:
    """Add `institutions.description` ({en, ru, uz})."""
    op.add_column(
        T,
        sa.Column("description", postgresql.JSONB(), nullable=True),
        schema=S,
    )


def downgrade() -> None:
    """Drop `institutions.description`."""
    op.drop_column(T, "description", schema=S)
