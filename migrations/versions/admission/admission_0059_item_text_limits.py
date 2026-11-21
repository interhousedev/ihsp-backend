"""admission: item organization 110 and description 600 characters.

Revision ID: admission_0059_item_text_limits
Revises: admission_0058_short_answers
Create Date: 2026-11-22 01:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0059_item_text_limits"
down_revision: str | Sequence[str] | None = "admission_0058_short_answers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
_OLD_DESCRIPTION = (
    "char_length(description) <= CASE WHEN kind = 'honor' THEN 100 ELSE 150 END"
)


def _swap(org: int, org_old: int, desc: str, size: int, size_old: int) -> None:
    op.drop_constraint(op.f("ck_items_org_length"), "items", schema=S)
    op.drop_constraint(op.f("ck_items_description_length"), "items", schema=S)
    op.alter_column(
        "items",
        "org",
        type_=sa.String(org),
        existing_type=sa.String(org_old),
        existing_server_default=sa.text("''"),
        schema=S,
    )
    op.alter_column(
        "items",
        "description",
        type_=sa.String(size),
        existing_type=sa.String(size_old),
        existing_server_default=sa.text("''"),
        schema=S,
    )
    op.create_check_constraint(
        op.f("ck_items_org_length"), "items", f"char_length(org) <= {org}", schema=S
    )
    op.create_check_constraint(
        op.f("ck_items_description_length"), "items", desc, schema=S
    )


def upgrade() -> None:
    """Widen organization to 110 and description to 600."""
    _swap(110, 100, "char_length(description) <= 600", 600, 150)


def downgrade() -> None:
    """Restore the old caps (longer text is cut to fit)."""
    op.execute(
        "UPDATE admission.items SET org = left(org, 100),"
        " description = left(description,"
        " CASE WHEN kind = 'honor' THEN 100 ELSE 150 END)"
    )
    _swap(100, 110, _OLD_DESCRIPTION, 150, 600)
