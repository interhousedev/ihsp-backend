"""Group rules that hide EMIS lesson sources.

A teacher can hide the EMIS sources of their lessons of a subject for one group:
`links.emis_hide_rules` keeps (teacher, subject, group), and the new column
`links.hidden_by_rule` marks the resources the rule hid, so turning the rule off
shows only those again and keeps manual hides. Downgrading drops both.

Revision ID: links_0004
Revises: links_0003
Create Date: 2026-10-21 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "links_0004"
down_revision: str | Sequence[str] | None = "links_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "links",
        sa.Column(
            "hidden_by_rule",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        schema="links",
    )
    op.create_table(
        "emis_hide_rules",
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint(
            "teacher_id", "subject_id", "group_id", name=op.f("pk_emis_hide_rules")
        ),
        schema="links",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("emis_hide_rules", schema="links")
    op.drop_column("links", "hidden_by_rule", schema="links")
