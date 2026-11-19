"""admission tests: the SAT Evidence-Based Reading and Writing catalog entry.

Revision ID: admission_0042_test_sat_erw
Revises: admission_0041_list_fee_status
Create Date: 2026-11-19 10:00:00.000000
"""

from collections.abc import Sequence

from app.shared.ids import new_id

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0042_test_sat_erw"
down_revision: str | Sequence[str] | None = "admission_0041_list_fee_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
KEY = "sat_erw"

CATALOG = sa.table(
    "test_catalog",
    sa.column("id", sa.Uuid()),
    sa.column("key", sa.String()),
    sa.column("names", postgresql.JSONB()),
    sa.column("sections", postgresql.JSONB()),
    sa.column("total", postgresql.JSONB()),
    sa.column("total_mode", sa.String()),
    sa.column("superscore", sa.Boolean()),
    sa.column("needs_label", sa.Boolean()),
    sa.column("needs_level", sa.Boolean()),
    sa.column("position", sa.Integer()),
    sa.column("active", sa.Boolean()),
    schema=S,
)

ROW = {
    "key": KEY,
    "names": {
        "uz": "SAT Oʼqish va yozish",
        "ru": "SAT Чтение и письмо",
        "en": "SAT Evidence-Based Reading and Writing",
    },
    "sections": [],
    "total": {
        "key": "total",
        "names": {"uz": "Jami", "ru": "Итого", "en": "Total"},
        "min": 200,
        "max": 800,
        "step": 10,
        "choices": [],
    },
    "total_mode": "manual",
    "superscore": False,
    "needs_label": False,
    "needs_level": False,
    "position": 11,
    "active": True,
}


def upgrade() -> None:
    """Seed the SAT Evidence-Based Reading and Writing catalog row."""
    op.bulk_insert(CATALOG, [{"id": new_id(), **ROW}])


def downgrade() -> None:
    """Remove the SAT Evidence-Based Reading and Writing catalog row."""
    op.execute(sa.delete(CATALOG).where(CATALOG.c.key == KEY))
