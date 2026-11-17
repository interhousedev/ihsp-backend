"""admission drop help requests and guest links.

Revision ID: admission_0031_drop_help
Revises: admission_0030_consult_profile
Create Date: 2026-11-21 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "admission_0031_drop_help"
down_revision: str | Sequence[str] | None = "admission_0030_consult_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

S = "admission"


def upgrade() -> None:
    """Drop help requests, their responses and the guest links with sessions."""
    for table in ("guest_sessions", "help_responses", "guest_links", "help_requests"):
        op.drop_table(table, schema=S)


def _ts(*names: str) -> list[sa.Column]:
    return [
        sa.Column(
            n,
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
        for n in names
    ]


def downgrade() -> None:
    """Recreate the four tables empty, as admission_0001 and 0006 left them."""
    op.create_table(
        "help_requests",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default="open", nullable=False
        ),
        sa.Column("helper_user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_ts("created_at", "updated_at"),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('website', 'design', 'proof', 'other')",
            name=op.f("ck_help_requests_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'assigned', 'accepted', 'declined', 'delivered', "
            "'closed', 'cancelled', 'expired')",
            name=op.f("ck_help_requests_status"),
        ),
        sa.CheckConstraint(
            "char_length(brief) <= 1000", name=op.f("ck_help_requests_brief_length")
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["admission.items.id"],
            name=op.f("fk_help_requests_item_id_items"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_help_requests")),
        schema=S,
    )
    for col in ("helper_user_id", "student_id"):
        op.create_index(
            op.f(f"ix_admission_help_requests_{col}"),
            "help_requests",
            [col],
            schema=S,
        )
    op.create_table(
        "guest_links",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("help_request_id", sa.Uuid(), nullable=False),
        sa.Column("scope", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=8), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "max_sessions", sa.Integer(), server_default=sa.text("5"), nullable=False
        ),
        sa.Column(
            "sessions_used", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=40), nullable=True),
        sa.Column("rotated_from", sa.Uuid(), nullable=True),
        sa.Column("claimed_by", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_ts("created_at", "updated_at"),
        sa.Column(
            "lock_version", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '60 days'",
            name=op.f("ck_guest_links_expires_at"),
        ),
        sa.CheckConstraint(
            "scope <@ ARRAY['activities:read', 'help:respond']::text[]",
            name=op.f("ck_guest_links_scope"),
        ),
        sa.CheckConstraint(
            "max_sessions BETWEEN 1 AND 20", name=op.f("ck_guest_links_max_sessions")
        ),
        sa.ForeignKeyConstraint(
            ["help_request_id"],
            ["admission.help_requests.id"],
            name=op.f("fk_guest_links_help_request_id_help_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guest_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_guest_links_token_hash")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_guest_links_student_id"),
        "guest_links",
        ["student_id"],
        schema=S,
    )
    op.create_table(
        "guest_sessions",
        sa.Column("guest_link_id", sa.Uuid(), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_ts("created_at", "updated_at"),
        sa.ForeignKeyConstraint(
            ["guest_link_id"],
            ["admission.guest_links.id"],
            name=op.f("fk_guest_sessions_guest_link_id_guest_links"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guest_sessions")),
        sa.UniqueConstraint(
            "session_hash", name=op.f("uq_guest_sessions_session_hash")
        ),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_guest_sessions_guest_link_id"),
        "guest_sessions",
        ["guest_link_id"],
        schema=S,
    )
    op.create_table(
        "help_responses",
        sa.Column("help_request_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("guest_link_id", sa.Uuid(), nullable=True),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_ts("created_at", "updated_at"),
        sa.CheckConstraint(
            "char_length(text) <= 2000", name=op.f("ck_help_responses_text_length")
        ),
        sa.ForeignKeyConstraint(
            ["guest_link_id"],
            ["admission.guest_links.id"],
            name=op.f("fk_help_responses_guest_link_id_guest_links"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["help_request_id"],
            ["admission.help_requests.id"],
            name=op.f("fk_help_responses_help_request_id_help_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_help_responses")),
        schema=S,
    )
    op.create_index(
        op.f("ix_admission_help_responses_help_request_id"),
        "help_responses",
        ["help_request_id"],
        schema=S,
    )
