"""Connectors may name the admission MCP server.

`admission` does not fit the VARCHAR(7) column, so it widens to VARCHAR(9) (the
length SQLAlchemy derives from the longest server name) and the CHECK gains it.

Revision ID: identity_0020
Revises: identity_0019
Create Date: 2026-11-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0020"
down_revision: str | Sequence[str] | None = "identity_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# op.f() marks the name final (the naming convention must not prefix it again).
_NAME = "ck_mcp_connectors_server"
_OLD = "server IN ('student', 'lms', 'admin', 'teacher', 'app')"
_NEW = "server IN ('student', 'lms', 'admin', 'teacher', 'app', 'admission')"


def upgrade() -> None:
    """Widen the column and recreate the CHECK with the admission server."""
    op.drop_constraint(op.f(_NAME), "mcp_connectors", schema="id", type_="check")
    op.alter_column(
        "mcp_connectors",
        "server",
        schema="id",
        type_=sa.String(length=9),
        existing_type=sa.String(length=7),
        existing_nullable=False,
    )
    op.create_check_constraint(op.f(_NAME), "mcp_connectors", _NEW, schema="id")


def downgrade() -> None:
    """Back to five servers; admission connectors are removed first."""
    op.execute("DELETE FROM id.mcp_connectors WHERE server = 'admission'")
    op.drop_constraint(op.f(_NAME), "mcp_connectors", schema="id", type_="check")
    op.alter_column(
        "mcp_connectors",
        "server",
        schema="id",
        type_=sa.String(length=7),
        existing_type=sa.String(length=9),
        existing_nullable=False,
    )
    op.create_check_constraint(op.f(_NAME), "mcp_connectors", _OLD, schema="id")
