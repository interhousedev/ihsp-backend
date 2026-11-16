"""admission programs: the opportunity kind `program`.

Catalog fields of programs (country, tuition, ranking ...) live in the JSON payload
of the entry, so only the kind check constraint changes.

Revision ID: admission_0013_programs
Revises: admission_0012
Create Date: 2026-11-21 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0013_programs"
down_revision: str | Sequence[str] | None = "admission_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
_OLD = "kind IN ('exam', 'certification', 'course', 'event', 'recurring')"
_NEW = "kind IN ('exam', 'certification', 'course', 'event', 'recurring', 'program')"


def _swap(condition: str) -> None:
    op.drop_constraint("ck_opportunities_kind", "opportunities", schema=S)
    op.create_check_constraint(
        op.f("ck_opportunities_kind"), "opportunities", condition, schema=S
    )


def upgrade() -> None:
    """Allow `program`."""
    _swap(_NEW)


def downgrade() -> None:
    """Forbid `program` again."""
    op.execute(f"DELETE FROM {S}.opportunities WHERE kind = 'program'")
    _swap(_OLD)
