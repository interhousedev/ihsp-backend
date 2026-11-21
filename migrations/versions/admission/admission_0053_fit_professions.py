"""admission: fit preference ratings and the professions plan (ikigai).

Revision ID: admission_0053_fit_professions
Revises: admission_0052_today
Create Date: 2026-11-21 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0053_fit_professions"
down_revision: str | Sequence[str] | None = "admission_0052_today"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def _stamps() -> list[sa.Column]:  # type: ignore[type-arg]
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
    """Create fit_preferences and profession_plans."""
    op.create_table(
        "fit_preferences",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column(
            "ratings",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_stamps(),
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_fit_preferences")),
        schema=S,
    )
    op.create_table(
        "profession_plans",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column(
            "chosen",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "ikigai",
            sa.dialects.postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_stamps(),
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_profession_plans")),
        schema=S,
    )


def downgrade() -> None:
    """Drop both tables."""
    op.drop_table("profession_plans", schema=S)
    op.drop_table("fit_preferences", schema=S)
