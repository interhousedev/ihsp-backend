"""users.emis_teacher_id links a teacher account to the teacher in EMIS.

Revision ID: identity_0002
Revises: identity_0001
Create Date: 2026-10-08 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0002"
down_revision: str | Sequence[str] | None = "identity_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable, unique EMIS teacher id (set when a timetable names them)."""
    op.add_column(
        "users",
        sa.Column("emis_teacher_id", sa.Integer(), nullable=True),
        schema="id",
    )
    op.create_unique_constraint(
        "uq_users_emis_teacher_id", "users", ["emis_teacher_id"], schema="id"
    )


def downgrade() -> None:
    """Drop the EMIS teacher id."""
    op.drop_constraint("uq_users_emis_teacher_id", "users", schema="id", type_="unique")
    op.drop_column("users", "emis_teacher_id", schema="id")
