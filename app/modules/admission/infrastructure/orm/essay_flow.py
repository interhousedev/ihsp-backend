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

__all__ = [
    "EssayGalleryRow",
    "EssayPracticeRow",
    "EssayShortAnswerRow",
    "EssaySlotRow",
    "IdeaFitRow",
    "PromptGroupLabelRow",
]


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


class EssayGalleryRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
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


class PromptGroupLabelRow(CreatedMixin, UpdatedMixin, Base):
    """The generated short name of a prompt group (public data, no student text)."""

    __tablename__ = "prompt_group_labels"
    __table_args__ = (S,)

    members_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    label_ru: Mapped[str] = mapped_column(String(80))
    label_en: Mapped[str] = mapped_column(String(80))
    label_uz: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(200), server_default="")


class IdeaFitRow(CreatedMixin, UpdatedMixin, Base):
    """A cached idea fit: prompt keys and scores only, keyed by a keyed text digest."""

    __tablename__ = "idea_fits"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    text_digest: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class EssayShortAnswerRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A student's short text for one supplemental prompt; `text` is sealed."""

    __tablename__ = "essay_short_answers"
    __table_args__ = (
        UniqueConstraint("student_id", "prompt_key", name="uq_essay_short_answers_key"),
        Index("ix_essay_short_answers_student_id", "student_id"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid)
    prompt_key: Mapped[str] = mapped_column(String(80))
    text: Mapped[bytes] = mapped_column(LargeBinary)  # sealed
    word_count: Mapped[int] = mapped_column(Integer)
