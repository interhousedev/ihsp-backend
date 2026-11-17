"""admission catalog: institution_type fact key, logo and alias columns, list cycle.

Revision ID: admission_0023_catalog_facts
Revises: admission_0022_uni_media
Create Date: 2026-11-17 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0023_catalog_facts"
down_revision: str | Sequence[str] | None = "admission_0022_uni_media"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Unify the fact key, add logo/alias columns and the list-entry cycle."""
    op.execute(
        "DELETE FROM admission.facts f WHERE f.key = 'study_type' AND EXISTS ("
        " SELECT 1 FROM admission.facts g WHERE g.entity_kind = f.entity_kind"
        " AND g.entity_id = f.entity_id AND g.key = 'institution_type')"
    )
    op.execute(
        "UPDATE admission.facts SET key = 'institution_type' WHERE key = 'study_type'"
    )
    op.add_column(
        "institutions",
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        schema=S,
    )
    op.add_column(
        "institutions",
        sa.Column("logo_zoom", sa.Float(), server_default="1.0", nullable=False),
        schema=S,
    )
    op.add_column(
        "institutions", sa.Column("logo_fit", sa.String(8), nullable=True), schema=S
    )
    op.add_column(
        "institutions", sa.Column("logo_aspect", sa.Float(), nullable=True), schema=S
    )
    op.create_check_constraint(
        op.f("ck_institutions_logo_zoom"),
        "institutions",
        "logo_zoom >= 0.5 AND logo_zoom <= 1.5",
        schema=S,
    )
    op.create_check_constraint(
        op.f("ck_institutions_logo_fit"),
        "institutions",
        "logo_fit IS NULL OR logo_fit IN ('circle', 'contain')",
        schema=S,
    )
    op.add_column(
        "list_entries", sa.Column("cycle", sa.String(7), nullable=True), schema=S
    )
    op.execute(
        "UPDATE admission.list_entries SET cycle ="
        " (CASE WHEN extract(month FROM created_at) >= 8"
        "  THEN extract(year FROM created_at) ELSE extract(year FROM created_at) - 1"
        " END)::int::text || '-' || lpad(((CASE WHEN extract(month FROM created_at)"
        " >= 8 THEN extract(year FROM created_at) + 1 ELSE extract(year FROM created_at)"
        " END)::int % 100)::text, 2, '0')"
    )
    op.create_check_constraint(
        op.f("ck_list_entries_cycle"),
        "list_entries",
        "cycle IS NULL OR cycle ~ '^[0-9]{4}-[0-9]{2}$'",
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_list_entries_cycle"), "list_entries", ["cycle"], schema=S
    )


def downgrade() -> None:
    """Drop the new columns; the fact key stays unified."""
    op.drop_index(op.f("ix_admission_list_entries_cycle"), "list_entries", schema=S)
    op.drop_constraint(op.f("ck_list_entries_cycle"), "list_entries", schema=S)
    op.drop_column("list_entries", "cycle", schema=S)
    op.drop_constraint(op.f("ck_institutions_logo_fit"), "institutions", schema=S)
    op.drop_constraint(op.f("ck_institutions_logo_zoom"), "institutions", schema=S)
    for col in ("logo_aspect", "logo_fit", "logo_zoom", "aliases"):
        op.drop_column("institutions", col, schema=S)
