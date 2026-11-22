"""admission: when a student last looked at the new programs on Today.

Revision ID: admission_0066_today_extras
Revises: admission_0065_country_facts
Create Date: 2026-11-23 07:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0066_today_extras"
down_revision: str | Sequence[str] | None = "admission_0065_country_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create `today_programs_seen`."""
    NN: dict[str, bool] = {"nullable": False}  # noqa: N806
    op.create_table(
        "today_programs_seen",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), **NN),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_today_programs_seen")),
        schema=S,
    )


def downgrade() -> None:
    """Drop the table."""
    op.drop_table("today_programs_seen", schema=S)
