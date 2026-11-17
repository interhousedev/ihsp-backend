"""Admission assistant chats: allow the `admission` assistant.

Revision ID: ai_0009
Revises: ai_0008
Create Date: 2026-12-10 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ai_0009"
down_revision: str | Sequence[str] | None = "ai_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_ASSISTANTS = "assistant IN ('student', 'admin', 'lms_author')"
NEW_ASSISTANTS = "assistant IN ('student', 'admin', 'lms_author', 'admission')"


def upgrade() -> None:
    """Widen the assistant check with `admission`."""
    op.drop_constraint(op.f("ck_chats_assistant"), "chats", schema="ai", type_="check")
    op.create_check_constraint(
        op.f("ck_chats_assistant"), "chats", NEW_ASSISTANTS, schema="ai"
    )


def downgrade() -> None:
    """Drop the admission chats and restore the old check."""
    op.execute("DELETE FROM ai.chats WHERE assistant = 'admission'")
    op.drop_constraint(op.f("ck_chats_assistant"), "chats", schema="ai", type_="check")
    op.create_check_constraint(
        op.f("ck_chats_assistant"), "chats", OLD_ASSISTANTS, schema="ai"
    )
