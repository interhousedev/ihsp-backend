"""Stored web pages and cached web queries: search answers from pages already found.

Revision ID: ai_0005
Revises: ai_0004
Create Date: 2026-10-11 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ai_0005"
down_revision: str | Sequence[str] | None = "ai_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ai.web_pages and ai.web_queries with their indexes."""
    op.create_table(
        "web_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("site", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("highlight", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "times_returned", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_web_pages")),
        sa.UniqueConstraint("url", name="uq_web_pages_url"),
        schema="ai",
    )
    op.create_index(
        "ix_web_pages_last_seen_at",
        "web_pages",
        ["last_seen_at"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "ix_web_pages_content_hash",
        "web_pages",
        ["content_hash"],
        unique=False,
        schema="ai",
    )
    op.create_table(
        "web_queries",
        sa.Column("cache_key", sa.CHAR(length=64), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("page_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
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
        sa.PrimaryKeyConstraint("cache_key", name=op.f("pk_web_queries")),
        schema="ai",
    )
    op.create_index(
        "ix_web_queries_created_at",
        "web_queries",
        ["created_at"],
        unique=False,
        schema="ai",
    )


def downgrade() -> None:
    """Drop the web page store and the query cache."""
    op.drop_index("ix_web_queries_created_at", table_name="web_queries", schema="ai")
    op.drop_table("web_queries", schema="ai")
    op.drop_index("ix_web_pages_content_hash", table_name="web_pages", schema="ai")
    op.drop_index("ix_web_pages_last_seen_at", table_name="web_pages", schema="ai")
    op.drop_table("web_pages", schema="ai")
