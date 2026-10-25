"""mail init

Revision ID: mail_0001
Revises:
Create Date: 2026-10-07 17:00:49.836748

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "mail_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("mail",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE SCHEMA IF NOT EXISTS mail")
    op.create_table(
        "mail_messages",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "direction",
            sa.Enum(
                "in", "out", name="direction", native_enum=False, create_constraint=True
            ),
            nullable=False,
        ),
        sa.Column("message_id", sa.String(length=998), nullable=False),
        sa.Column("in_reply_to", sa.String(length=998), nullable=True),
        sa.Column(
            "references",
            sa.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column(
            "to", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "cc", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("subject", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("snippet", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("raw_file_id", sa.Uuid(), nullable=True),
        sa.Column(
            "attachment_file_ids",
            sa.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("spam_score", sa.REAL(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "received",
                "spam",
                "queued",
                "sent",
                "bounced",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mail_messages")),
        sa.UniqueConstraint(
            "user_id",
            "direction",
            "message_id",
            name="uq_mail_messages_user_direction_message_id",
        ),
        schema="mail",
    )
    op.create_index(
        "ix_mail_messages_attachment_file_ids",
        "mail_messages",
        ["attachment_file_ids"],
        unique=False,
        schema="mail",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_mail_messages_spam_created_at",
        "mail_messages",
        ["created_at"],
        unique=False,
        schema="mail",
        postgresql_where=sa.text("status = 'spam'"),
    )
    op.create_index(
        "ix_mail_messages_user_id_occurred_at",
        "mail_messages",
        ["user_id", "occurred_at"],
        unique=False,
        schema="mail",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_mail_messages_user_id_occurred_at",
        table_name="mail_messages",
        schema="mail",
    )
    op.drop_index(
        "ix_mail_messages_spam_created_at",
        table_name="mail_messages",
        schema="mail",
        postgresql_where=sa.text("status = 'spam'"),
    )
    op.drop_index(
        "ix_mail_messages_attachment_file_ids",
        table_name="mail_messages",
        schema="mail",
        postgresql_using="gin",
    )
    op.drop_table("mail_messages", schema="mail")
    op.execute("DROP SCHEMA IF EXISTS mail CASCADE")
