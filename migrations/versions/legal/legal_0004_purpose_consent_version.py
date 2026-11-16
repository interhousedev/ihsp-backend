"""legal purpose consents: the version of the purpose text a grant answers.

Revision ID: legal_0004
Revises: legal_0003
Create Date: 2026-11-18 10:00:00.000000

Existing grants answer version 1; a grant of an older version than the current
one of its purpose no longer counts, so the subject is asked again.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "legal_0004"
down_revision: str | Sequence[str] | None = "legal_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the version column; every existing grant is version 1."""
    op.execute(
        "ALTER TABLE legal.purpose_consents "
        "ADD COLUMN version integer NOT NULL DEFAULT 1"
    )


def downgrade() -> None:
    """Drop the column."""
    op.execute("ALTER TABLE legal.purpose_consents DROP COLUMN version")
