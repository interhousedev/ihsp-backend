"""admission essay review links and the sealed feedback left through them.

Revision ID: admission_0038_essay_invites
Revises: admission_0037_exemplars
Create Date: 2026-11-21 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "admission_0038_essay_invites"
down_revision: str | Sequence[str] | None = "admission_0037_exemplars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"
AUDIENCE = "audience IN ('classmate', 'parent', 'counselor', 'other')"


def _now() -> list[sa.Column[object]]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
        for name in ("created_at", "updated_at")
    ]


def _index(table: str, column: str) -> None:
    op.create_index(
        op.f(f"ix_{S}_{table}_{column}"), table, [column], unique=False, schema=S
    )


def upgrade() -> None:
    """Create essay_invites and essay_feedback."""
    op.create_table(
        "essay_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("essay_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.LargeBinary(), nullable=True),
        sa.Column("audience", sa.String(length=20), nullable=False),
        sa.Column("can_comment", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
        *_now(),
        sa.CheckConstraint(AUDIENCE, name=op.f("ck_essay_invites_audience")),
        sa.ForeignKeyConstraint(
            ["essay_id"],
            [f"{S}.essays.id"],
            name=op.f("fk_essay_invites_essay_id_essays"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_essay_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_essay_invites_token_hash")),
        schema=S,
    )
    _index("essay_invites", "essay_id")
    _index("essay_invites", "student_id")
    op.create_table(
        "essay_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("essay_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("invite_id", sa.Uuid(), nullable=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("quote", sa.LargeBinary(), nullable=True),
        sa.Column("anchor_start", sa.Integer(), nullable=True),
        sa.Column("anchor_end", sa.Integer(), nullable=True),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("author_name", sa.LargeBinary(), nullable=False),
        sa.Column("audience", sa.String(length=20), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *_now(),
        sa.CheckConstraint(AUDIENCE, name=op.f("ck_essay_feedback_audience")),
        sa.ForeignKeyConstraint(
            ["essay_id"],
            [f"{S}.essays.id"],
            name=op.f("fk_essay_feedback_essay_id_essays"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invite_id"],
            [f"{S}.essay_invites.id"],
            name=op.f("fk_essay_feedback_invite_id_essay_invites"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            [f"{S}.essay_feedback.id"],
            name=op.f("fk_essay_feedback_parent_id_essay_feedback"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_essay_feedback")),
        schema=S,
    )
    for column in ("essay_id", "student_id", "invite_id", "parent_id"):
        _index("essay_feedback", column)


def downgrade() -> None:
    """Drop both tables."""
    for column in ("parent_id", "invite_id", "student_id", "essay_id"):
        op.drop_index(
            op.f(f"ix_{S}_essay_feedback_{column}"), "essay_feedback", schema=S
        )
    op.drop_table("essay_feedback", schema=S)
    for column in ("student_id", "essay_id"):
        op.drop_index(op.f(f"ix_{S}_essay_invites_{column}"), "essay_invites", schema=S)
    op.drop_table("essay_invites", schema=S)
