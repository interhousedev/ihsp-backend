"""admission institution media: logo and cover URLs.

Revision ID: admission_0022_uni_media
Revises: admission_0021_preferences
Create Date: 2026-11-16 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0022_uni_media"
down_revision: str | Sequence[str] | None = "admission_0021_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Add the nullable media columns."""
    op.add_column(
        "institutions", sa.Column("logo_url", sa.String(2000), nullable=True), schema=S
    )
    op.add_column(
        "institutions", sa.Column("cover_url", sa.String(2000), nullable=True), schema=S
    )
    op.create_check_constraint(
        op.f("ck_institutions_media_https"),
        "institutions",
        "(logo_url IS NULL OR logo_url LIKE 'https://%')"
        " AND (cover_url IS NULL OR cover_url LIKE 'https://%')",
        schema=S,
    )


def downgrade() -> None:
    """Drop the media columns."""
    op.drop_constraint(op.f("ck_institutions_media_https"), "institutions", schema=S)
    op.drop_column("institutions", "cover_url", schema=S)
    op.drop_column("institutions", "logo_url", schema=S)
