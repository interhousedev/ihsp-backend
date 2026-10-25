"""ORM model of ai.flashcards."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    REAL,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class Flashcard(IdMixin, TimestampMixin, Base):
    """One card with its spaced repetition state (the set has one owner)."""

    __tablename__ = "flashcards"
    __table_args__ = (
        Index("ix_flashcards_set_id_due_at", "set_id", "due_at"),
        Index("ix_flashcards_set_id_position", "set_id", "position"),
        {"schema": "ai"},
    )

    set_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("ai.flashcard_sets.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(
        Enum(
            "new",
            "learning",
            "review",
            "relearning",
            name="state",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'new'"),
    )
    step: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interval_days: Mapped[float] = mapped_column(REAL, server_default=text("0"))
    ease: Mapped[float] = mapped_column(REAL, server_default=text("2.5"))
    reps: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    lapses: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
