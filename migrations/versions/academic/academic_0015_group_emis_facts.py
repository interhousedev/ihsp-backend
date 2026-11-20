"""Groups keep the facts EMIS gives about them, so later reads need no EMIS call.

The EMIS group name, the course, the direction, the speciality and the institution
name are filled whenever a student's EMIS profile is read (the marks sync). All are
nullable: a group read before the first profile has none of them.

Revision ID: academic_0015
Revises: academic_0014
Create Date: 2026-11-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "academic_0015"
down_revision: str | Sequence[str] | None = "academic_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable EMIS fact columns to academic.groups."""
    op.add_column(
        "groups",
        sa.Column("emis_name", sa.String(64), nullable=True),
        schema="academic",
    )
    op.add_column(
        "groups",
        sa.Column("course", sa.SmallInteger(), nullable=True),
        schema="academic",
    )
    op.add_column(
        "groups",
        sa.Column("direction", sa.String(255), nullable=True),
        schema="academic",
    )
    op.add_column(
        "groups",
        sa.Column("speciality", sa.String(255), nullable=True),
        schema="academic",
    )
    op.add_column(
        "groups",
        sa.Column("institution_name", postgresql.JSONB(), nullable=True),
        schema="academic",
    )


def downgrade() -> None:
    """Drop the EMIS fact columns."""
    for column in ("institution_name", "speciality", "direction", "course"):
        op.drop_column("groups", column, schema="academic")
    op.drop_column("groups", "emis_name", schema="academic")
