"""admission list entry round SCEA (restrictive early action).

Revision ID: admission_0039_round_scea
Revises: admission_0038_essay_invites
Create Date: 2026-11-22 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.sql.elements import conv

# revision identifiers, used by Alembic.
revision: str = "admission_0039_round_scea"
down_revision: str | Sequence[str] | None = "admission_0038_essay_invites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
NAME = conv("ck_list_entries_round")
_OLD = "round IN ('RD', 'EA', 'ED', 'ED2', 'REA', 'rolling', 'other')"
_NEW = "round IN ('RD', 'EA', 'ED', 'ED2', 'REA', 'SCEA', 'rolling', 'other')"


def _swap(condition: str) -> None:
    op.drop_constraint(NAME, "list_entries", schema=S, type_="check")
    op.create_check_constraint(NAME, "list_entries", condition, schema=S)


def upgrade() -> None:
    """Allow round SCEA."""
    _swap(_NEW)


def downgrade() -> None:
    """Map SCEA rows to REA, then restore the old check."""
    op.execute(f"UPDATE {S}.list_entries SET round = 'REA' WHERE round = 'SCEA'")
    _swap(_OLD)
