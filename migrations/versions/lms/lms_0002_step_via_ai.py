"""Steps can be created and changed by the AI author assistant.

Revision ID: lms_0002
Revises: lms_0001
Create Date: 2026-10-08 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "lms_0002"
down_revision: str | Sequence[str] | None = "lms_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("created_via", "draft_updated_via")


def _replace_checks(values: str) -> None:
    """Recreate the two enumeration checks of ``course_steps`` with new values."""
    for column in COLUMNS:
        name = op.f(f"ck_course_steps_{column}")
        op.drop_constraint(name, "course_steps", schema="lms", type_="check")
        op.create_check_constraint(
            name, "course_steps", f"{column} IN ({values})", schema="lms"
        )


def upgrade() -> None:
    """Allow ``ai`` next to ``ui`` and ``mcp`` as the origin of a step change."""
    _replace_checks("'ui', 'mcp', 'ai'")


def downgrade() -> None:
    """Turn AI changes into MCP changes (also machine-made), forbid ``ai`` again."""
    for column in COLUMNS:
        op.execute(
            f"UPDATE lms.course_steps SET {column} = 'mcp' WHERE {column} = 'ai'"
        )
    _replace_checks("'ui', 'mcp'")
