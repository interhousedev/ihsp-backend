"""Default materials of subjects.

The admin adds files, links and library books to an EMIS subject id
(`subject_default_materials`); every student's subject notebook of that subject gets a
copy. No foreign key to the subjects: the id may come before the subject does. The
file and the library item belong to other modules, so they are plain ids too.

Revision ID: notebooks_0008
Revises: notebooks_0007
Create Date: 2026-10-10 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notebooks_0008"
down_revision: str | Sequence[str] | None = "notebooks_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHAPE = (
    "(kind = 'file' AND file_id IS NOT NULL "
    "AND url IS NULL AND library_item_id IS NULL) "
    "OR (kind = 'link' AND url IS NOT NULL "
    "AND file_id IS NULL AND library_item_id IS NULL) "
    "OR (kind = 'library_item' AND library_item_id IS NOT NULL "
    "AND file_id IS NULL AND url IS NULL)"
)


def _kind() -> sa.Enum:
    """The `kind` column type (VARCHAR plus CHECK), as the other enumerations."""
    return sa.Enum(
        "file",
        "link",
        "library_item",
        name="kind",
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "subject_default_materials",
        sa.Column("edu_subject_id", sa.Integer(), nullable=False),
        sa.Column("kind", _kind(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("library_item_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(SHAPE, name=op.f("ck_subject_default_materials_shape")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subject_default_materials")),
        schema="notebooks",
    )
    op.create_index(
        "ix_subject_default_materials_edu_subject_id_position",
        "subject_default_materials",
        ["edu_subject_id", "position"],
        unique=False,
        schema="notebooks",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_subject_default_materials_edu_subject_id_position",
        table_name="subject_default_materials",
        schema="notebooks",
    )
    op.drop_table("subject_default_materials", schema="notebooks")
