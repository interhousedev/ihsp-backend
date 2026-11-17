"""ORM of supplemental essay prompts."""

from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    SCHEMA,
    CreatedMixin,
    UpdatedMixin,
    max_len,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["SuppPromptRow"]


class SuppPromptRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """One supplemental prompt of an institution in one admission cycle."""

    __tablename__ = "supp_prompts"
    __table_args__ = (
        UniqueConstraint("institution_id", "cycle", "position"),
        CheckConstraint("cycle ~ '^[0-9]{4}-[0-9]{2}$'", name="cycle_format"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint(
            "word_limit IS NULL OR word_limit BETWEEN 1 AND 5000",
            name="word_limit_range",
        ),
        CheckConstraint(
            "source_url IS NULL OR source_url LIKE 'https://%'",
            name="source_url_https",
        ),
        max_len("prompt", 4000),
        Index("ix_supp_prompts_institution_cycle", "institution_id", "cycle"),
        {"schema": SCHEMA},
    )

    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{SCHEMA}.institutions.id", ondelete="CASCADE")
    )
    cycle: Mapped[str] = mapped_column(String(7))
    position: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(Text)
    word_limit: Mapped[int | None] = mapped_column(Integer)
    required: Mapped[bool] = mapped_column(Boolean)
    source_url: Mapped[str | None] = mapped_column(String(500))
