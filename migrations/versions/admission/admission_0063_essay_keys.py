"""admission: essay key ledger (generation, one backup per generation, rotation).

Revision ID: admission_0063_essay_keys
Revises: admission_0062_profession_custom
Create Date: 2026-11-23 04:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "admission_0063_essay_keys"
down_revision: str | Sequence[str] | None = "admission_0062_profession_custom"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Create `essay_key_state` (one row, generation 1) and `essay_key_exports`."""
    NN: dict[str, bool] = {"nullable": False}  # noqa: N806
    op.create_table(
        "essay_key_state",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default=sa.text("1"), **NN),
        sa.Column(
            "rotation_state", sa.String(8), server_default=sa.text("'idle'"), **NN
        ),
        sa.Column("rotation_total", sa.Integer(), server_default=sa.text("0"), **NN),
        sa.Column("rotation_done", sa.Integer(), server_default=sa.text("0"), **NN),
        sa.Column(
            "rotation_unreadable", sa.Integer(), server_default=sa.text("0"), **NN
        ),
        sa.Column("rotation_by", sa.Uuid(), nullable=True),
        sa.Column("rotation_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotation_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), **NN
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_essay_key_state_single_row")),
        sa.CheckConstraint(
            "rotation_state IN ('idle', 'running', 'done', 'failed')",
            name=op.f("ck_essay_key_state_rotation_state"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_essay_key_state")),
        schema=S,
    )
    op.execute(f"INSERT INTO {S}.essay_key_state (id) VALUES (1)")
    op.create_table(
        "essay_key_exports",
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exported_by", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("generation", name=op.f("pk_essay_key_exports")),
        schema=S,
    )


def downgrade() -> None:
    """Drop the key ledger."""
    op.drop_table("essay_key_exports", schema=S)
    op.drop_table("essay_key_state", schema=S)
