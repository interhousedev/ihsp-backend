"""Connectors may name the teacher and app MCP servers.

The 0001 CHECK allowed only student, lms and admin, so a teacher connector could
not be stored. The column is VARCHAR(7); `teacher` and `app` fit.

Revision ID: identity_0014
Revises: identity_0013
Create Date: 2026-11-14 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0014"
down_revision: str | Sequence[str] | None = "identity_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# op.f(): the name is final, the naming convention must not prefix it again.
_NAME = op.f("ck_mcp_connectors_server")
_OLD = "server IN ('student', 'lms', 'admin')"
_NEW = "server IN ('student', 'lms', 'admin', 'teacher', 'app')"


def upgrade() -> None:
    """Recreate the CHECK with every server."""
    op.drop_constraint(_NAME, "mcp_connectors", schema="id", type_="check")
    op.create_check_constraint(_NAME, "mcp_connectors", _NEW, schema="id")


def downgrade() -> None:
    """Back to the three servers; connectors of the others are removed first."""
    op.execute("DELETE FROM id.mcp_connectors WHERE server IN ('teacher', 'app')")
    op.drop_constraint(_NAME, "mcp_connectors", schema="id", type_="check")
    op.create_check_constraint(_NAME, "mcp_connectors", _OLD, schema="id")
