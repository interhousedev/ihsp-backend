"""Message feedback and chat tier.

Revision ID: ai_0002
Revises: ai_0001
Create Date: 2026-10-08 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ai_0002"
down_revision: str | Sequence[str] | None = "ai_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the thumbs on assistant messages and the model tier of a chat."""
    op.add_column(
        "chat_messages",
        sa.Column("feedback", sa.SmallInteger(), nullable=True),
        schema="ai",
    )
    op.add_column(
        "chat_messages",
        sa.Column("feedback_comment", sa.Text(), nullable=True),
        schema="ai",
    )
    op.create_check_constraint(
        op.f("ck_chat_messages_feedback_value"),
        "chat_messages",
        "feedback IN (1, -1)",
        schema="ai",
    )
    op.create_check_constraint(
        op.f("ck_chat_messages_feedback_comment"),
        "chat_messages",
        "feedback_comment IS NULL OR "
        "(feedback IS NOT NULL AND char_length(feedback_comment) <= 500)",
        schema="ai",
    )
    op.add_column(
        "chats",
        sa.Column(
            "tier",
            sa.Enum(
                "fast",
                "smart",
                name="tier",
                native_enum=False,
                create_constraint=False,
            ),
            server_default=sa.text("'fast'"),
            nullable=False,
        ),
        schema="ai",
    )
    op.create_check_constraint(
        op.f("ck_chats_tier"),
        "chats",
        "tier IN ('fast', 'smart')",
        schema="ai",
    )


def downgrade() -> None:
    """Drop the tier and the feedback columns with their checks."""
    op.drop_constraint(op.f("ck_chats_tier"), "chats", schema="ai", type_="check")
    op.drop_column("chats", "tier", schema="ai")
    op.drop_constraint(
        op.f("ck_chat_messages_feedback_comment"),
        "chat_messages",
        schema="ai",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_chat_messages_feedback_value"),
        "chat_messages",
        schema="ai",
        type_="check",
    )
    op.drop_column("chat_messages", "feedback_comment", schema="ai")
    op.drop_column("chat_messages", "feedback", schema="ai")
