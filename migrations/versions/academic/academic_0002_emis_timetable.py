"""EMIS timetable: where entries come from, and the EMIS details of a lesson.

Revision ID: academic_0002
Revises: academic_0001
Create Date: 2026-10-08 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "academic_0002"
down_revision: str | Sequence[str] | None = "academic_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add entries.source and lessons.kind, emis_class_id and emis_topic."""
    op.add_column(
        "timetable_entries",
        sa.Column(
            "source",
            sa.Enum(
                "manual",
                "emis",
                name="source",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'manual'"),
            nullable=False,
        ),
        schema="academic",
    )
    op.add_column(
        "lessons",
        sa.Column(
            "kind",
            sa.Enum(
                "lecture",
                "practice",
                "midterm",
                "final",
                "other",
                name="kind",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'other'"),
            nullable=False,
        ),
        schema="academic",
    )
    op.add_column(
        "lessons",
        sa.Column("emis_class_id", sa.BigInteger(), nullable=True),
        schema="academic",
    )
    op.add_column(
        "lessons",
        sa.Column("emis_topic", sa.Text(), nullable=True),
        schema="academic",
    )
    op.create_index(
        "ix_lessons_emis_class_id",
        "lessons",
        ["emis_class_id"],
        unique=False,
        schema="academic",
    )


def downgrade() -> None:
    """Drop the EMIS columns."""
    op.drop_index("ix_lessons_emis_class_id", table_name="lessons", schema="academic")
    op.drop_column("lessons", "emis_topic", schema="academic")
    op.drop_column("lessons", "emis_class_id", schema="academic")
    op.drop_column("lessons", "kind", schema="academic")
    op.drop_column("timetable_entries", "source", schema="academic")
