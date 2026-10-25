"""Group curriculum from EMIS: the header and the subjects of each semester.

Revision ID: academic_0005
Revises: academic_0004
Create Date: 2026-10-10 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "academic_0005"
down_revision: str | Sequence[str] | None = "academic_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create group_curriculum and group_curriculum_subject."""
    op.create_table(
        "group_curriculum",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("emis_curriculum_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("speciality", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("direction", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("edu_form", sa.String(length=128), nullable=True),
        sa.Column("language_code", sa.String(length=8), nullable=True),
        sa.Column("rating_min", sa.SmallInteger(), nullable=True),
        sa.Column("rating_max", sa.SmallInteger(), nullable=True),
        sa.Column("semesters_count", sa.SmallInteger(), nullable=True),
        sa.Column(
            "semester_dates",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "subject_totals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "exams",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "vocational",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["academic.groups.id"],
            name=op.f("fk_group_curriculum_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("group_id", name=op.f("pk_group_curriculum")),
        schema="academic",
    )
    op.create_table(
        "group_curriculum_subject",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("semester_number", sa.SmallInteger(), nullable=False),
        sa.Column("emis_subject_id", sa.Integer(), nullable=False),
        sa.Column("name", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("subject_type_id", sa.SmallInteger(), nullable=True),
        sa.Column("study_hours", sa.Integer(), nullable=True),
        sa.Column("class_hours", sa.Integer(), nullable=True),
        sa.Column("independent_hours", sa.Integer(), nullable=True),
        sa.Column(
            "is_separated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["academic.groups.id"],
            name=op.f("fk_group_curriculum_subject_group_id_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "group_id",
            "semester_number",
            "emis_subject_id",
            name=op.f("pk_group_curriculum_subject"),
        ),
        schema="academic",
    )
    op.create_index(
        "ix_group_curriculum_subject_group_id",
        "group_curriculum_subject",
        ["group_id"],
        unique=False,
        schema="academic",
    )


def downgrade() -> None:
    """Drop both tables."""
    op.drop_index(
        "ix_group_curriculum_subject_group_id",
        table_name="group_curriculum_subject",
        schema="academic",
    )
    op.drop_table("group_curriculum_subject", schema="academic")
    op.drop_table("group_curriculum", schema="academic")
