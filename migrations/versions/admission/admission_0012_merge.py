"""admission merge: join the review, calendar, essays, career and opportunities heads.

Revision ID: admission_0012
Revises: admission_0007, admission_0008, admission_0009, admission_0010, admission_0011
Create Date: 2026-11-20 12:00:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "admission_0012"
down_revision: str | Sequence[str] | None = (
    "admission_0007",
    "admission_0008",
    "admission_0009",
    "admission_0010",
    "admission_0011",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
