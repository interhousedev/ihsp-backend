"""course broadcasts

Revision ID: notify_0006
Revises: notify_0005
Create Date: 2026-10-10 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "notify_0006"
down_revision: str | Sequence[str] | None = "notify_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the history of messages that course admins send to students."""
    op.create_table(
        "course_broadcasts",
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_course_broadcasts")),
        schema="notify",
    )
    op.create_index(
        "ix_course_broadcasts_course_id_created_at",
        "course_broadcasts",
        ["course_id", "created_at"],
        unique=False,
        schema="notify",
    )


def downgrade() -> None:
    """Drop the history."""
    op.drop_index(
        "ix_course_broadcasts_course_id_created_at",
        table_name="course_broadcasts",
        schema="notify",
    )
    op.drop_table("course_broadcasts", schema="notify")
