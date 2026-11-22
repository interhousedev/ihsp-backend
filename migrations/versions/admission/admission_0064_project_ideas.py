"""admission: project-idea runs of a student and the curated project helpers.

Revision ID: admission_0064_project_ideas
Revises: admission_0063_essay_keys
Create Date: 2026-11-23 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "admission_0064_project_ideas"
down_revision: str | Sequence[str] | None = "admission_0063_essay_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def _json(name: str, default: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text(default),
        nullable=False,
    )


def upgrade() -> None:
    """Create `project_idea_runs` and `project_helpers`."""
    NN: dict[str, bool] = {"nullable": False}  # noqa: N806
    op.create_table(
        "project_idea_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=2), nullable=False),
        sa.Column("brief", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _json("projects", "'[]'::jsonb"),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("search_used", sa.Boolean(), server_default=sa.text("false"), **NN),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.CheckConstraint(
            "locale IN ('uz', 'ru', 'en')", name=op.f("ck_project_idea_runs_locale")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_idea_runs")),
        schema=S,
    )
    op.create_index(
        "ix_project_idea_runs_student_created",
        "project_idea_runs",
        ["student_id", "created_at"],
        schema=S,
    )
    op.create_table(
        "project_helpers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        _json("description", "'{}'::jsonb"),
        _json("tags", "'[]'::jsonb"),
        _json("help_types", "'[]'::jsonb"),
        _json("expertise_areas", "'[]'::jsonb"),
        _json("contacts", "'{}'::jsonb"),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), **NN),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.CheckConstraint(
            "kind IN ('person', 'organization')",
            name=op.f("ck_project_helpers_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_helpers")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_project_helpers_active"),
        "project_helpers",
        ["active"],
        schema=S,
    )


def downgrade() -> None:
    """Drop both tables."""
    op.drop_table("project_helpers", schema=S)
    op.drop_table("project_idea_runs", schema=S)
