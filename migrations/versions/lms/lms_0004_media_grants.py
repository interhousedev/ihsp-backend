"""Revocable links to course media issued through MCP.

Revision ID: lms_0004
Revises: lms_0003
Create Date: 2026-11-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "lms_0004"
down_revision: str | Sequence[str] | None = "lms_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create lms.media_grants."""
    op.create_table(
        "media_grants",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("block_id", sa.String(length=100), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("issued_to", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "redeem_count", sa.Integer(), server_default=sa.text("0"), nullable=False
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
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["lms.courses.id"],
            name=op.f("fk_media_grants_course_id_courses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_grants")),
        sa.UniqueConstraint("token_hash", name="uq_media_grants_token_hash"),
        sa.UniqueConstraint(
            "issued_to", "step_id", "block_id", name="uq_media_grants_issued_block"
        ),
        schema="lms",
    )


def downgrade() -> None:
    """Drop lms.media_grants."""
    op.drop_table("media_grants", schema="lms")
