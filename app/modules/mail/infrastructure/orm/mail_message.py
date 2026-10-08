"""ORM model of mail.mail_messages."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    REAL,
    DateTime,
    Enum,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class MailMessage(IdMixin, TimestampMixin, Base):
    """An email in a user's mailbox; the raw message is a file in S3."""

    __tablename__ = "mail_messages"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "direction",
            "message_id",
            name="uq_mail_messages_user_direction_message_id",
        ),
        Index("ix_mail_messages_user_id_occurred_at", "user_id", "occurred_at"),
        Index(
            "ix_mail_messages_attachment_file_ids",
            "attachment_file_ids",
            postgresql_using="gin",
        ),
        Index(
            "ix_mail_messages_spam_created_at",
            "created_at",
            postgresql_where=text("status = 'spam'"),
        ),
        {"schema": "mail"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    direction: Mapped[str] = mapped_column(
        Enum(
            "in",
            "out",
            name="direction",
            native_enum=False,
            create_constraint=True,
        )
    )
    message_id: Mapped[str] = mapped_column(String(998))
    in_reply_to: Mapped[str | None] = mapped_column(String(998))
    references: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
    from_address: Mapped[str] = mapped_column(String(320))
    to: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    cc: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    subject: Mapped[str] = mapped_column(Text, server_default=text("''"))
    snippet: Mapped[str] = mapped_column(Text, server_default=text("''"))
    raw_file_id: Mapped[UUID | None] = mapped_column(Uuid)
    attachment_file_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'")
    )
    spam_score: Mapped[float | None] = mapped_column(REAL)
    status: Mapped[str] = mapped_column(
        Enum(
            "received",
            "spam",
            "queued",
            "sent",
            "bounced",
            "failed",
            name="status",
            native_enum=False,
            create_constraint=True,
        )
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Check results (SPF, DKIM, DMARC) and names of skipped attachments.
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
