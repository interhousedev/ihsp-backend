"""ORM model of ai.flashcard_sets."""

from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class FlashcardSet(IdMixin, TimestampMixin, Base):
    """A set of flash cards with one owner (others copy it).

    The table lives in schema ``ai`` (spec), but ``source_chat_id`` has no
    foreign key: the ``flashcards`` migration branch does not depend on ``ai``.
    """

    __tablename__ = "flashcard_sets"
    __table_args__ = (
        Index("ix_flashcard_sets_owner_id", "owner_id"),
        {"schema": "ai"},
    )

    owner_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(
        Enum(
            "manual",
            "ai",
            "mcp",
            "copied",
            name="source",
            native_enum=False,
            create_constraint=True,
        )
    )
    source_chat_id: Mapped[UUID | None] = mapped_column(Uuid)
    copied_from_set_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("ai.flashcard_sets.id", ondelete="SET NULL")
    )
    new_per_day: Mapped[int] = mapped_column(SmallInteger, server_default=text("20"))
    reviews_per_day: Mapped[int] = mapped_column(
        SmallInteger, server_default=text("200")
    )
    card_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
