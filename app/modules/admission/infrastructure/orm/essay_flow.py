"""ORM of the essay flow: daily practice, the shared gallery and the match slots."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    SCHEMA,
    CreatedMixin,
    S,
    UpdatedMixin,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["EssayGalleryRow", "EssayPracticeRow", "EssaySlotRow"]


class EssayPracticeRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A day's free writing; `body` and `evaluation` (JSON) are sealed."""

    __tablename__ = "essay_practice"
    __table_args__ = (
        UniqueConstraint("student_id", "day"),
        Index("ix_essay_practice_student_id", "student_id"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid)
    day: Mapped[dt.date] = mapped_column(Date)
    theme: Mapped[str] = mapped_column(String(40))
    body: Mapped[bytes] = mapped_column(LargeBinary)  # sealed
    evaluation: Mapped[bytes | None] = mapped_column(LargeBinary)  # sealed JSON
    model: Mapped[str | None] = mapped_column(String(200))


class EssayGalleryRow(IdMixin, CreatedMixin, Base):
    """An essay version published to other students, without the author's name."""

    __tablename__ = "essay_gallery"
    __table_args__ = (
        UniqueConstraint("essay_id"),
        Index("ix_essay_gallery_student_id", "student_id"),
        S,
    )

    essay_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.essays.id", ondelete="CASCADE")
    )
    student_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    prompt_text: Mapped[str | None] = mapped_column(Text)
    word_limit: Mapped[int | None] = mapped_column(Integer)
    targets: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'")
    )


class EssaySlotRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """An essay placed into one prompt slot (`ps` or `supp:<n>`) of a university."""

    __tablename__ = "essay_slots"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "institution_id", "slot", name="uq_essay_slots_slot"
        ),
        UniqueConstraint(
            "student_id", "institution_id", "essay_id", name="uq_essay_slots_essay"
        ),
        CheckConstraint("slot ~ '^(ps|supp:[0-9]{1,3})$'", name="slot_format"),
        Index("ix_essay_slots_student_id", "student_id"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.institutions.id", ondelete="CASCADE")
    )
    slot: Mapped[str] = mapped_column(String(10))
    essay_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.essays.id", ondelete="CASCADE")
    )
