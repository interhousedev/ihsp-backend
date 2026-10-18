"""certificates custom fields: field definitions on types, values on entries.

Revision ID: certificates_0002
Revises: certificates_0001
Create Date: 2026-10-18 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "certificates_0002"
down_revision: str | Sequence[str] | None = "certificates_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the jsonb columns for custom fields and their values."""
    op.add_column(
        "types",
        sa.Column(
            "custom_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema="certificates",
    )
    op.add_column(
        "entries",
        sa.Column(
            "custom_values",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema="certificates",
    )


def downgrade() -> None:
    """Drop the custom field columns."""
    op.drop_column("entries", "custom_values", schema="certificates")
    op.drop_column("types", "custom_fields", schema="certificates")
