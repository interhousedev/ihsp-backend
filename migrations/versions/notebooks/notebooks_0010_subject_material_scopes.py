"""Subject materials of teachers: for all their groups or for one group.

`subject_default_materials` gets a `scope` (admin: every subject notebook of the EMIS
subject id; teacher_subject: the groups a teacher has for the subject; group: one group
or subgroup of a teacher), the `teacher_id` and, for groups, `group_id` and `subgroup`.
Existing rows are administration materials.

Revision ID: notebooks_0010
Revises: notebooks_0009
Create Date: 2026-10-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0010"
down_revision: str | Sequence[str] | None = "notebooks_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPE_SHAPE = (
    "(scope = 'admin' AND teacher_id IS NULL AND group_id IS NULL "
    "AND subgroup IS NULL) "
    "OR (scope = 'teacher_subject' AND teacher_id IS NOT NULL "
    "AND group_id IS NULL AND subgroup IS NULL) "
    "OR (scope = 'group' AND teacher_id IS NOT NULL AND group_id IS NOT NULL)"
)
TABLE = "subject_default_materials"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        TABLE,
        sa.Column(
            "scope",
            sa.Enum(
                "admin",
                "teacher_subject",
                "group",
                name="scope",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'admin'"),
            nullable=False,
        ),
        schema="notebooks",
    )
    op.add_column(
        TABLE, sa.Column("teacher_id", sa.Uuid(), nullable=True), schema="notebooks"
    )
    op.add_column(
        TABLE, sa.Column("group_id", sa.Uuid(), nullable=True), schema="notebooks"
    )
    op.add_column(
        TABLE,
        sa.Column("subgroup", sa.SmallInteger(), nullable=True),
        schema="notebooks",
    )
    op.create_check_constraint(
        op.f("ck_subject_default_materials_scope_shape"),
        TABLE,
        SCOPE_SHAPE,
        schema="notebooks",
    )
    op.create_index(
        "ix_subject_default_materials_teacher_id_edu_subject_id",
        TABLE,
        ["teacher_id", "edu_subject_id"],
        unique=False,
        schema="notebooks",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"DELETE FROM notebooks.{TABLE} WHERE scope <> 'admin'")
    op.drop_index(
        "ix_subject_default_materials_teacher_id_edu_subject_id",
        table_name=TABLE,
        schema="notebooks",
    )
    op.drop_constraint(
        op.f("ck_subject_default_materials_scope_shape"),
        TABLE,
        schema="notebooks",
        type_="check",
    )
    op.drop_column(TABLE, "subgroup", schema="notebooks")
    op.drop_column(TABLE, "group_id", schema="notebooks")
    op.drop_column(TABLE, "teacher_id", schema="notebooks")
    op.drop_column(TABLE, "scope", schema="notebooks")
