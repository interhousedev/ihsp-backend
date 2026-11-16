"""admission assistant: threads and messages.

Revision ID: admission_0018_assistant
Revises: admission_0017_student_rag
Create Date: 2026-11-23 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0018_assistant"
down_revision: str | Sequence[str] | None = "admission_0017_student_rag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def _ts(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _json(name: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )


def upgrade() -> None:
    """Create the assistant tables."""
    op.create_table(
        "assistant_threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        _ts("updated_at"),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_threads")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_assistant_threads_student_id"),
        "assistant_threads",
        ["student_id"],
        schema=S,
    )
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=9), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        _json("citations"),
        _json("actions"),
        _ts("created_at"),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name=op.f("ck_assistant_messages_role")
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["admission.assistant_threads.id"],
            name=op.f("fk_assistant_messages_thread_id_assistant_threads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assistant_messages")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_assistant_messages_thread_id"),
        "assistant_messages",
        ["thread_id"],
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_assistant_messages_student_id"),
        "assistant_messages",
        ["student_id"],
        schema=S,
    )


def downgrade() -> None:
    """Drop the assistant tables."""
    op.drop_table("assistant_messages", schema=S)
    op.drop_table("assistant_threads", schema=S)
