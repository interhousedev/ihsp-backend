"""AI request registry, prompt defaults, and version source/diff/size columns.

Revision ID: ai_0011
Revises: ai_0010_connectors_pipelines
Create Date: 2026-11-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ai_0011"
down_revision: str | Sequence[str] | None = "ai_0010_connectors_pipelines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the request registry and prompt defaults; extend the prompt versions."""
    op.create_table(
        "ai_requests",
        sa.Column("id", sa.String(length=120), nullable=False),
        sa.Column("owner_app", sa.String(length=32), nullable=False),
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("template_id", sa.String(length=128), nullable=False),
        sa.Column(
            "args_schema",
            postgresql.JSONB(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "tools", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False
        ),
        sa.Column("summary", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "retired", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "code_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_requests")),
        schema="ai",
    )
    op.create_table(
        "prompt_defaults",
        sa.Column("task", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("hash", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("task", "name", name=op.f("pk_prompt_defaults")),
        schema="ai",
    )
    op.add_column(
        "prompt_versions",
        sa.Column(
            "source",
            sa.String(length=8),
            server_default=sa.text("'admin'"),
            nullable=False,
        ),
        schema="ai",
    )
    op.create_check_constraint(
        "ck_prompt_versions_source",
        "prompt_versions",
        "source IN ('admin', 'code')",
        schema="ai",
    )
    op.add_column(
        "prompt_versions", sa.Column("diff", sa.Text(), nullable=True), schema="ai"
    )
    op.add_column(
        "prompt_versions",
        sa.Column("chars", sa.Integer(), server_default=sa.text("0"), nullable=False),
        schema="ai",
    )
    op.add_column(
        "prompt_versions",
        sa.Column(
            "tokens_est", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        schema="ai",
    )
    op.execute(
        "UPDATE ai.prompt_versions SET chars = char_length(text), "
        "tokens_est = ceil(char_length(text) / 4.0)::int"
    )


def downgrade() -> None:
    """Drop the request registry, prompt defaults and the version columns."""
    op.drop_column("prompt_versions", "tokens_est", schema="ai")
    op.drop_column("prompt_versions", "chars", schema="ai")
    op.drop_column("prompt_versions", "diff", schema="ai")
    op.drop_constraint(
        "ck_prompt_versions_source", "prompt_versions", schema="ai", type_="check"
    )
    op.drop_column("prompt_versions", "source", schema="ai")
    op.drop_table("prompt_defaults", schema="ai")
    op.drop_table("ai_requests", schema="ai")
