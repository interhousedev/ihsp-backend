"""posts init: the bot post tree and the /start mode of Telegram users.

`posts.posts` keeps the tree (exactly one root: a partial unique index on is_root;
the application creates the root on first use). `posts.bot_user_modes` keeps the
choice a Telegram user made on /start (guest or student).

Revision ID: posts_0001
Revises:
Create Date: 2026-10-25 12:00:00.000000

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "posts_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("posts",)
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[Any]]:
    return [
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
    ]


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS posts")
    op.create_table(
        "posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "body",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "audience", sa.String(length=16), server_default="both", nullable=False
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "published", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "is_root", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "buttons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "audience IN ('guest', 'student', 'both')",
            name=op.f("ck_posts_audience"),
        ),
        sa.CheckConstraint(
            "(parent_id IS NULL) = is_root", name=op.f("ck_posts_root_parent")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posts")),
        schema="posts",
    )
    op.create_index("ix_posts_slug", "posts", ["slug"], unique=True, schema="posts")
    op.create_index("ix_posts_parent_id", "posts", ["parent_id"], schema="posts")
    op.create_index(
        "ix_posts_single_root",
        "posts",
        ["is_root"],
        unique=True,
        schema="posts",
        postgresql_where=sa.text("is_root"),
    )
    op.create_table(
        "bot_user_modes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "mode IN ('guest', 'student')", name=op.f("ck_bot_user_modes_mode")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_user_modes")),
        schema="posts",
    )
    op.create_index(
        "ix_bot_user_modes_telegram_user_id",
        "bot_user_modes",
        ["telegram_user_id"],
        unique=True,
        schema="posts",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("bot_user_modes", schema="posts")
    op.drop_table("posts", schema="posts")
    op.execute("DROP SCHEMA IF EXISTS posts")
