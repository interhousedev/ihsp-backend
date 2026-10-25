"""Login cues: EMIS logins pre-registered by administrators for students.

Revision ID: identity_0008
Revises: identity_0007
Create Date: 2026-10-25 12:00:00.000000

The login is stored as a Vault Transit ciphertext; only its last two characters
are kept in clear. ``group_id`` refers to ``academic.groups`` without a foreign key,
because branches never depend on each other across schemas.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "identity_0008"
down_revision: str | Sequence[str] | None = "identity_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create id.login_cues and the index of the open cues per group."""
    op.create_table(
        "login_cues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("emis_login_enc", sa.Text(), nullable=False),
        sa.Column("login_tail", sa.String(length=2), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
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
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_by_user_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_cues")),
        schema="id",
    )
    op.create_index(
        "ix_login_cues_group_open",
        "login_cues",
        ["group_id"],
        unique=False,
        schema="id",
        postgresql_where=sa.text("consumed_at IS NULL"),
    )


def downgrade() -> None:
    """Drop the login cues table."""
    op.drop_index("ix_login_cues_group_open", table_name="login_cues", schema="id")
    op.drop_table("login_cues", schema="id")
