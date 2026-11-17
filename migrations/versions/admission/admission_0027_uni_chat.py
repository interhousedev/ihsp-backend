"""admission university chats: links, default prompts, web research cache.

Revision ID: admission_0027_uni_chat
Revises: admission_0026_activity_grades
Create Date: 2026-11-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0027_uni_chat"
down_revision: str | Sequence[str] | None = "admission_0026_activity_grades"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create the three tables."""
    op.create_table(
        "uni_chats",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "auto_run_pending",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("auto_ran_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["admission.institutions.id"],
            name=op.f("fk_uni_chats_institution_id_institutions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uni_chats")),
        sa.UniqueConstraint("chat_id", name=op.f("uq_uni_chats_chat_id")),
        sa.UniqueConstraint(
            "student_id", "institution_id", name=op.f("uq_uni_chats_student_id")
        ),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_uni_chats_student_id"),
        "uni_chats",
        ["student_id"],
        unique=False,
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_uni_chats_institution_id"),
        "uni_chats",
        ["institution_id"],
        unique=False,
        schema=S,
    )
    op.create_table(
        "uni_default_prompts",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
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
        sa.CheckConstraint(
            "char_length(prompt) <= 2000",
            name=op.f("ck_uni_default_prompts_prompt_length"),
        ),
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_uni_default_prompts")),
        schema=S,
    )
    op.create_table(
        "uni_web_cache",
        sa.Column("kind", sa.String(6), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
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
        sa.CheckConstraint(
            "kind IN ('search', 'page')", name=op.f("ck_uni_web_cache_kind")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uni_web_cache")),
        sa.UniqueConstraint("kind", "cache_key", name=op.f("uq_uni_web_cache_kind")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_uni_web_cache_fetched_at"),
        "uni_web_cache",
        ["fetched_at"],
        unique=False,
        schema=S,
    )


def downgrade() -> None:
    """Drop the three tables."""
    op.drop_index(
        op.f("ix_admission_uni_web_cache_fetched_at"),
        table_name="uni_web_cache",
        schema=S,
    )
    op.drop_table("uni_web_cache", schema=S)
    op.drop_table("uni_default_prompts", schema=S)
    op.drop_index(
        op.f("ix_admission_uni_chats_institution_id"), table_name="uni_chats", schema=S
    )
    op.drop_index(
        op.f("ix_admission_uni_chats_student_id"), table_name="uni_chats", schema=S
    )
    op.drop_table("uni_chats", schema=S)
