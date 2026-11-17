"""admission wider logo zoom range and the advice cache kind.

Revision ID: admission_0032_logo_zoom_advice
Revises: admission_0031_drop_help
Create Date: 2026-11-22 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0032_logo_zoom_advice"
down_revision: str | Sequence[str] | None = "admission_0031_drop_help"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def _swap(zoom_max: str, kinds: str) -> None:
    zoom = op.f("ck_institutions_logo_zoom")
    kind = op.f("ck_uni_web_cache_kind")
    op.drop_constraint(zoom, "institutions", schema=S, type_="check")
    op.create_check_constraint(
        zoom, "institutions", f"logo_zoom >= 0.5 AND logo_zoom <= {zoom_max}", schema=S
    )
    op.drop_constraint(kind, "uni_web_cache", schema=S, type_="check")
    op.create_check_constraint(kind, "uni_web_cache", f"kind IN ({kinds})", schema=S)


def upgrade() -> None:
    """Allow logo zoom up to 3 and the `advice` cache kind."""
    _swap("3", "'search', 'page', 'advice'")


def downgrade() -> None:
    """Restore the narrower checks (rows outside them must be fixed first)."""
    _swap("1.5", "'search', 'page'")
