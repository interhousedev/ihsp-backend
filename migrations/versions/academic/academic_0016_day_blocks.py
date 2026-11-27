"""Non-lesson blocks of the school day (lunch, second lunch, breaks, assemblies).

Revision ID: academic_0016
Revises: academic_0015
Create Date: 2026-11-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0016"
down_revision: str | Sequence[str] | None = "academic_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create academic.day_blocks."""
    op.create_table(
        "day_blocks",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "lunch",
                "second_lunch",
                "break",
                "assembly",
                "other",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("starts_at", sa.Time(), nullable=False),
        sa.Column("ends_at", sa.Time(), nullable=False),
        sa.Column("weekdays", sa.ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "all",
                "course",
                "groups",
                name="scope",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("course", sa.SmallInteger(), nullable=True),
        sa.Column(
            "group_ids",
            sa.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ends_at > starts_at", name=op.f("ck_day_blocks_time_order")
        ),
        sa.CheckConstraint(
            "cardinality(weekdays) > 0 AND weekdays <@ ARRAY[1,2,3,4,5]::smallint[]",
            name=op.f("ck_day_blocks_weekdays"),
        ),
        sa.CheckConstraint(
            "(scope = 'course') = (course IS NOT NULL)",
            name=op.f("ck_day_blocks_course_scope"),
        ),
        sa.CheckConstraint(
            "scope <> 'groups' OR cardinality(group_ids) > 0",
            name=op.f("ck_day_blocks_groups_scope"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_day_blocks")),
        schema="academic",
    )


def downgrade() -> None:
    """Drop academic.day_blocks."""
    op.drop_table("day_blocks", schema="academic")
