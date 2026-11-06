"""What an EMIS lesson material is: homework, classwork, video or other.

Until now the kind survived only as a title prefix. The column is nullable (people's
uploads have none); EMIS rows are filled once from their titles.

Revision ID: links_0006
Revises: links_0005
Create Date: 2026-11-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "links_0006"
down_revision: str | Sequence[str] | None = "links_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMIS_AUTHOR_ID = "00000000-0000-0000-0000-00000000e015"
CHECK = "lesson_material_kind IN ('homework', 'classwork', 'video', 'other')"


def upgrade() -> None:
    """Add the column and fill it for EMIS rows from their title."""
    op.add_column(
        "links",
        sa.Column("lesson_material_kind", sa.String(length=9), nullable=True),
        schema="links",
    )
    op.create_check_constraint(
        op.f("ck_links_lesson_material_kind"), "links", CHECK, schema="links"
    )
    op.execute(f"""
        UPDATE links.links
        SET lesson_material_kind = CASE
            WHEN title LIKE 'Homework:%' THEN 'homework'
            WHEN title LIKE 'Classwork:%' THEN 'classwork'
            WHEN title LIKE '%(video)' THEN 'video'
            ELSE 'other'
        END
        WHERE owner_id = '{EMIS_AUTHOR_ID}' AND lesson_id IS NOT NULL
        """)


def downgrade() -> None:
    """Drop the column; the titles still hold the kind."""
    op.drop_constraint(
        op.f("ck_links_lesson_material_kind"), "links", schema="links", type_="check"
    )
    op.drop_column("links", "lesson_material_kind", schema="links")
