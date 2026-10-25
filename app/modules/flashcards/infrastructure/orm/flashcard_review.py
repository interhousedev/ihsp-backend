"""ORM model of ai.flashcard_reviews."""

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
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column


class FlashcardReview(IdMixin, TimestampMixin, Base):
    """One answered card: the review log behind the heatmap and the streaks.

    A deleted card leaves its rows (``card_id`` becomes NULL), because the days
    the student studied do not change when a card is edited out; deleting the
    set deletes its log. ``user_id`` has no foreign key (as ``owner_id`` of the
    set): the ``flashcards`` migration branch does not depend on ``identity``.
    """

    __tablename__ = "flashcard_reviews"
    __table_args__ = (
        Index("ix_flashcard_reviews_user_id_reviewed_at", "user_id", "reviewed_at"),
        Index("ix_flashcard_reviews_set_id_reviewed_at", "set_id", "reviewed_at"),
        {"schema": "ai"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    set_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("ai.flashcard_sets.id", ondelete="CASCADE")
    )
    card_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("ai.flashcards.id", ondelete="SET NULL")
    )
    rating: Mapped[str] = mapped_column(
        Enum(
            "again",
            "hard",
            "medium",
            "easy",
            name="rating",
            native_enum=False,
            create_constraint=True,
        )
    )
    state_before: Mapped[str] = mapped_column(
        Enum(
            "new",
            "learning",
            "review",
            "relearning",
            name="state_before",
            native_enum=False,
            create_constraint=True,
        )
    )
    interval_after_days: Mapped[float] = mapped_column(REAL)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
