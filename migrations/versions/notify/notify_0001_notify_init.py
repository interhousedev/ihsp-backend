"""notify init

Revision ID: notify_0001
Revises:
Create Date: 2026-10-07 17:00:38.129744

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "notify_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("notify",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS notify")
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "marks",
                "result_drop",
                "result_below",
                "lesson_resources",
                "lesson_prompt",
                "lesson_changed",
                "mail",
                "mail_bounced",
                "broadcast",
                "emis_reauth",
                "files_expiring",
                "telegram_linked",
                "otp_reset_requested",
                "login_failures",
                "account_closing",
                "mail_suspended",
                "sync_alert",
                name="type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("broadcast_id", sa.Uuid(), nullable=True),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "sending",
                "sent",
                "partial",
                "failed",
                "skipped",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "deliveries",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint("dedupe_key", name="uq_notifications_dedupe_key"),
        schema="notify",
    )
    op.create_index(
        "ix_notifications_broadcast_id",
        "notifications",
        ["broadcast_id"],
        unique=False,
        schema="notify",
        postgresql_where=sa.text("broadcast_id IS NOT NULL"),
    )
    op.create_index(
        "ix_notifications_status_next_attempt_at",
        "notifications",
        ["status", "next_attempt_at"],
        unique=False,
        schema="notify",
    )
    op.create_index(
        "ix_notifications_status_scheduled_at",
        "notifications",
        ["status", "scheduled_at"],
        unique=False,
        schema="notify",
    )
    op.create_index(
        "ix_notifications_user_id_created_at",
        "notifications",
        ["user_id", "created_at"],
        unique=False,
        schema="notify",
    )
    op.create_index(
        "ix_notifications_user_id_unread",
        "notifications",
        ["user_id"],
        unique=False,
        schema="notify",
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_notifications_user_id_unread",
        table_name="notifications",
        schema="notify",
        postgresql_where=sa.text("read_at IS NULL"),
    )
    op.drop_index(
        "ix_notifications_user_id_created_at",
        table_name="notifications",
        schema="notify",
    )
    op.drop_index(
        "ix_notifications_status_scheduled_at",
        table_name="notifications",
        schema="notify",
    )
    op.drop_index(
        "ix_notifications_status_next_attempt_at",
        table_name="notifications",
        schema="notify",
    )
    op.drop_index(
        "ix_notifications_broadcast_id",
        table_name="notifications",
        schema="notify",
        postgresql_where=sa.text("broadcast_id IS NOT NULL"),
    )
    op.drop_table("notifications", schema="notify")
    op.execute("DROP SCHEMA IF EXISTS notify CASCADE")
