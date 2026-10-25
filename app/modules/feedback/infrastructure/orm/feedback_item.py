"""ORM model of feedback.items."""

from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import CheckConstraint, Index, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

KINDS = ("idea", "bug", "other")
AREAS = (
    "id", "my", "staff", "admin", "lms", "library", "share", "bot", "ai",
    "notebooks", "mail", "other",
)  # fmt: skip
STATUSES = ("new", "in_review", "planned", "done", "rejected")
SOURCES = ("web", "bot")


def in_values(column: str, values: tuple[str, ...]) -> str:
    """SQL of a CHECK that the column holds one of the values."""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class FeedbackItemRow(IdMixin, TimestampMixin, Base):
    """One feedback item; attachments are file ids of the files module."""

    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint(in_values("kind", KINDS), name="kind"),
        CheckConstraint(in_values("area", AREAS), name="area"),
        CheckConstraint(in_values("status", STATUSES), name="status"),
        CheckConstraint(in_values("source", SOURCES), name="source"),
        Index("ix_items_reporter_id_created_at", "reporter_id", "created_at"),
        Index("ix_items_created_at_id", "created_at", "id"),
        Index("ix_items_status", "status"),
        {"schema": "feedback"},
    )

    reporter_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    area: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'new'"))
    source: Mapped[str] = mapped_column(String(8))
    page_url: Mapped[str | None] = mapped_column(String(500))
    attachment_file_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'")
    )
