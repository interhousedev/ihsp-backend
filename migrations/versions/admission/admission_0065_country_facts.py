"""admission: country facts (cost, climate, visa, safety and more per country).

Revision ID: admission_0065_country_facts
Revises: admission_0064_project_ideas
Create Date: 2026-11-23 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "admission_0065_country_facts"
down_revision: str | Sequence[str] | None = "admission_0064_project_ideas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create `country_facts`."""
    NN: dict[str, bool] = {"nullable": False}  # noqa: N806
    op.create_table(
        "country_facts",
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("as_of", sa.String(7), nullable=False),
        sa.Column(
            "facts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            **NN,
        ),
        sa.Column("status", sa.String(8), server_default=sa.text("'draft'"), **NN),
        sa.Column("verified_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'verified')",
            name=op.f("ck_country_facts_status"),
        ),
        sa.PrimaryKeyConstraint("country", name=op.f("pk_country_facts")),
        schema=S,
    )


def downgrade() -> None:
    """Drop `country_facts`."""
    op.drop_table("country_facts", schema=S)
