"""A student may be groupless: students.group_id is nullable, set null on delete.

Deleting a group detaches its students instead of blocking on the foreign key.

Revision ID: academic_0014
Revises: academic_0013
Create Date: 2026-11-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0014"
down_revision: str | Sequence[str] | None = "academic_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = "fk_students_group_id_groups"


def upgrade() -> None:
    """Allow a null group and detach students when the group is deleted."""
    op.alter_column(
        "students",
        "group_id",
        existing_type=sa.Uuid(),
        nullable=True,
        schema="academic",
    )
    op.drop_constraint(FK, "students", schema="academic", type_="foreignkey")
    op.create_foreign_key(
        FK,
        "students",
        "groups",
        ["group_id"],
        ["id"],
        source_schema="academic",
        referent_schema="academic",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Restore the required group; groupless students must be placed first."""
    op.drop_constraint(FK, "students", schema="academic", type_="foreignkey")
    op.create_foreign_key(
        FK,
        "students",
        "groups",
        ["group_id"],
        ["id"],
        source_schema="academic",
        referent_schema="academic",
    )
    op.alter_column(
        "students",
        "group_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema="academic",
    )
