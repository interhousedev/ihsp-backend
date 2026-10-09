"""ORM models of reports, history, sanctions and book suggestions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.library.domain.enums import (
    EventKind,
    ReportReason,
    ReportStatus,
    SanctionKind,
    SuggestionStatus,
)
from app.modules.library.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ItemReport(IdMixin, TimestampMixin, Base):
    """A user's report about an item; the reporter is never shown to the uploader."""

    __tablename__ = "item_reports"
    __table_args__ = (
        Index(
            "ix_item_reports_open_unique",
            "item_id",
            "reporter_id",
            "reason",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_item_reports_status_created_at", "status", "created_at"),
        {"schema": "library"},
    )

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.items.id", ondelete="CASCADE")
    )
    reporter_id: Mapped[UUID] = mapped_column(Uuid)
    reporter_role: Mapped[str | None] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(str_enum(ReportReason, "reason"))
    text: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        str_enum(ReportStatus, "status"), server_default="open"
    )
    handled_by: Mapped[UUID | None] = mapped_column(Uuid)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action: Mapped[str | None] = mapped_column(String(30))


class ItemEvent(TimestampMixin, Base):
    """Append-only history of an item."""

    __tablename__ = "item_events"
    __table_args__ = ({"schema": "library"},)

    item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("library.items.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(str_enum(EventKind, "kind"))
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Sanction(IdMixin, TimestampMixin, Base):
    """A warning or an upload ban; active while `until` is in the future."""

    __tablename__ = "sanctions"
    __table_args__ = (
        Index("ix_sanctions_user_id_until", "user_id", "until"),
        {"schema": "library"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(str_enum(SanctionKind, "kind"))
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    item_id: Mapped[UUID | None] = mapped_column(Uuid)
    set_by: Mapped[UUID] = mapped_column(Uuid)


class BookSuggestion(IdMixin, TimestampMixin, Base):
    """A book suggested by a teacher or a student, waiting in the librarian queue."""

    __tablename__ = "book_suggestions"
    __table_args__ = (
        Index("ix_book_suggestions_status_created_at", "status", "created_at"),
        {"schema": "library"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[UUID | None] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        str_enum(SuggestionStatus, "status"), server_default="new"
    )
    handled_by: Mapped[UUID | None] = mapped_column(Uuid)
