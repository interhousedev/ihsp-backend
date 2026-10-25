"""ORM models of the reader state: shelf, progress, annotations, plans, lesson links."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.library.domain.enums import (
    AnnotationColor,
    AnnotationKind,
    ShelfState,
)
from app.modules.library.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ShelfEntry(IdMixin, TimestampMixin, Base):
    """An item on a user's shelf (UniLibrary records too, as links)."""

    __tablename__ = "shelf_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_shelf_entries_user_id"),
        Index("ix_shelf_entries_user_id_state", "user_id", "state"),
        Index("ix_shelf_entries_item_id", "item_id"),
        {"schema": "library"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    item_id: Mapped[UUID] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(str_enum(ShelfState, "state"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReadingProgress(TimestampMixin, Base):
    """Where a user stopped in an item (books and materials only)."""

    __tablename__ = "reading_progress"
    __table_args__ = (
        Index("ix_reading_progress_user_id_opened_at", "user_id", "opened_at"),
        {"schema": "library"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    file_id: Mapped[UUID] = mapped_column(Uuid)
    locator: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    seconds_read: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    client_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Annotation(IdMixin, TimestampMixin, Base):
    """A private highlight, note or bookmark."""

    __tablename__ = "annotations"
    __table_args__ = (
        UniqueConstraint("user_id", "client_id", name="uq_annotations_user_id"),
        Index(
            "ix_annotations_user_id_item_id_updated_at",
            "user_id",
            "item_id",
            "updated_at",
        ),
        {"schema": "library"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    item_id: Mapped[UUID] = mapped_column(Uuid)
    file_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(str_enum(AnnotationKind, "kind"))
    locator: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    quote: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str] = mapped_column(
        str_enum(AnnotationColor, "color"), server_default="yellow"
    )
    client_id: Mapped[UUID] = mapped_column(Uuid)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BookPlan(IdMixin, TimestampMixin, Base):
    """Sections of a textbook planned for a subject and year of study."""

    __tablename__ = "book_plans"
    __table_args__ = (
        UniqueConstraint(
            "subject_id", "year_of_study", "item_id", name="uq_book_plans_subject_id"
        ),
        {"schema": "library"},
    )

    subject_id: Mapped[UUID] = mapped_column(Uuid)
    year_of_study: Mapped[int] = mapped_column(SmallInteger)
    item_id: Mapped[UUID] = mapped_column(Uuid)
    sections: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )


class LessonItemRef(IdMixin, TimestampMixin, Base):
    """A lesson follows a section of a book; never changes `Lesson.topic`."""

    __tablename__ = "lesson_item_refs"
    __table_args__ = (
        Index("ix_lesson_item_refs_lesson_id", "lesson_id"),
        {"schema": "library"},
    )

    lesson_id: Mapped[UUID] = mapped_column(Uuid)
    item_id: Mapped[UUID] = mapped_column(Uuid)
    section_label: Mapped[str] = mapped_column(String(200))
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    set_by: Mapped[UUID] = mapped_column(Uuid)
