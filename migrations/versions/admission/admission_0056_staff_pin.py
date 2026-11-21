"""admission staff pin: one counselor-pinned action per student.

Revision ID: admission_0056_staff_pin
Revises: admission_0055_today_snooze
Create Date: 2026-11-21 23:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0056_staff_pin"
down_revision: str | Sequence[str] | None = "admission_0055_today_snooze"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create staff_pins."""
    op.create_table(
        "staff_pins",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("href", sa.String(length=500), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("pinned_by", sa.Uuid(), nullable=False),
        sa.Column("pinned_by_name", sa.String(length=160), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_staff_pins")),
        schema=S,
    )


def downgrade() -> None:
    """Drop staff_pins."""
    op.drop_table("staff_pins", schema=S)
