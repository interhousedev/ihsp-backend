"""Course author chats: the chat scope and the lms_author assistant.

Revision ID: ai_0003
Revises: ai_0002
Create Date: 2026-10-08 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ai_0003"
down_revision: str | Sequence[str] | None = "ai_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ASSISTANTS = "assistant IN ('student', 'admin')"
NEW_ASSISTANTS = "assistant IN ('student', 'admin', 'lms_author')"


def upgrade() -> None:
    """Add `scope` (the course workspace of an author chat) and allow lms_author."""
    op.add_column(
        "chats",
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="ai",
    )
    op.create_index(
        "ix_chats_scope_course_id",
        "chats",
        [sa.text("(scope ->> 'course_id')")],
        unique=False,
        schema="ai",
    )
    op.drop_constraint(op.f("ck_chats_assistant"), "chats", schema="ai", type_="check")
    op.alter_column(
        "chats",
        "assistant",
        existing_type=sa.String(length=7),
        type_=sa.String(length=10),
        existing_nullable=False,
        schema="ai",
    )
    op.create_check_constraint(
        op.f("ck_chats_assistant"), "chats", NEW_ASSISTANTS, schema="ai"
    )


def downgrade() -> None:
    """Drop the author chats, then the scope; the assistant check goes back."""
    op.execute("DELETE FROM ai.chats WHERE assistant = 'lms_author'")
    op.drop_constraint(op.f("ck_chats_assistant"), "chats", schema="ai", type_="check")
    op.alter_column(
        "chats",
        "assistant",
        existing_type=sa.String(length=10),
        type_=sa.String(length=7),
        existing_nullable=False,
        schema="ai",
    )
    op.create_check_constraint(
        op.f("ck_chats_assistant"), "chats", OLD_ASSISTANTS, schema="ai"
    )
    op.drop_index("ix_chats_scope_course_id", table_name="chats", schema="ai")
    op.drop_column("chats", "scope", schema="ai")
