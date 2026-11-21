"""admission_0045: honors get the shared category, a level and a certificate link.

Revision ID: admission_0045_honor_categories
Revises: admission_0044_program_fields
Create Date: 2026-11-21 10:00:00.000000

An honor's ``category`` used to hold its recognition level (school, regional, ...).
The level moves to the new ``level`` column and ``category`` becomes the category shared
with certificate types ("other" for the existing honors). ``certificate_entry_id`` links
an honor made from a platform certificate. ``honor_dismissals`` keeps the certificates a
student dismissed from the honor suggestions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0045_honor_categories"
down_revision: str | None = "admission_0044_program_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Add the columns and table; move honor levels."""
    op.add_column("items", sa.Column("level", sa.String(16), nullable=True), schema=S)
    op.add_column(
        "items", sa.Column("certificate_entry_id", sa.Uuid(), nullable=True), schema=S
    )
    op.execute(
        "UPDATE admission.items SET level = category, category = 'other' "
        "WHERE kind = 'honor' AND category IS NOT NULL"
    )
    op.create_table(
        "honor_dismissals",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("certificate_entry_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "student_id",
            "certificate_entry_id",
            name=op.f("pk_honor_dismissals"),
        ),
        schema=S,
    )


def downgrade() -> None:
    """Undo."""
    op.drop_table("honor_dismissals", schema=S)
    op.execute(
        "UPDATE admission.items SET category = level "
        "WHERE kind = 'honor' AND level IS NOT NULL"
    )
    op.execute(
        "UPDATE admission.items SET category = NULL "
        "WHERE kind = 'honor' AND level IS NULL"
    )
    op.drop_column("items", "certificate_entry_id", schema=S)
    op.drop_column("items", "level", schema=S)
