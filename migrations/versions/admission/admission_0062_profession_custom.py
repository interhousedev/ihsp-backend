"""admission: professions a student typed in.

Revision ID: admission_0062_profession_custom
Revises: admission_0061_inst_description
Create Date: 2026-11-22 04:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "admission_0062_profession_custom"
down_revision: str | Sequence[str] | None = "admission_0061_inst_description"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
T = "profession_plans"


def upgrade() -> None:
    """Add `profession_plans.custom` (a list of filled custom professions)."""
    op.add_column(
        T,
        sa.Column(
            "custom",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=S,
    )


def downgrade() -> None:
    """Drop `profession_plans.custom`."""
    op.drop_column(T, "custom", schema=S)
