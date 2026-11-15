"""Library: private page markup (pen, highlighter, shapes) per user and item.

Revision ID: library_0005
Revises: library_0004
Create Date: 2026-11-15 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "library_0005"
down_revision: str | Sequence[str] | None = "library_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create `library.reader_markup`."""
    op.create_table(
        "reader_markup",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column(
            "pages",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
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
        sa.PrimaryKeyConstraint("user_id", "item_id", name=op.f("pk_reader_markup")),
        schema="library",
    )


def downgrade() -> None:
    """Drop it."""
    op.drop_table("reader_markup", schema="library")
