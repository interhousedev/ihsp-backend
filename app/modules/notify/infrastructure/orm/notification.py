"""ORM model of notify.notifications."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    DateTime,
    Enum,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Notification(IdMixin, TimestampMixin, Base):
    """The bot's outbox and the web notification center in one table."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_notifications_dedupe_key"),
        Index("ix_notifications_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_notifications_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
        Index(
            "ix_notifications_user_id_unread",
            "user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
        Index(
            "ix_notifications_broadcast_id",
            "broadcast_id",
            postgresql_where=text("broadcast_id IS NOT NULL"),
        ),
        {"schema": "notify"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    type: Mapped[str] = mapped_column(
        Enum(
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
            "notebook_artifact_ready",
            "assessment_reminder",
            "library_item_approved",
            "library_item_changes_requested",
            "library_item_rejected",
            "library_item_unpublished",
            "library_queue_waiting",
            "library_report_filed",
            "library_reading_list_new",
            "curator_exam_mark",
            "library_suggestion_approved",
            "library_suggestion_declined",
            "student_sync_failed",
            name="type",
            native_enum=False,
            create_constraint=True,
        )
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    dedupe_key: Mapped[str] = mapped_column(String(255))
    broadcast_id: Mapped[UUID | None] = mapped_column(Uuid)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    status: Mapped[str] = mapped_column(
        Enum(
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
        server_default=text("'pending'"),
    )
    deliveries: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
