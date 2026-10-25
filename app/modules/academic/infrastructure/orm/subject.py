"""ORM model of academic.subjects."""

from typing import Any

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import Boolean, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Subject(IdMixin, TimestampMixin, Base):
    """A school subject; ``name`` is ``{"uz": ..., "ru": ..., "en": ...}``."""

    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("emis_subject_id", name="uq_subjects_emis_subject_id"),
        {"schema": "academic"},
    )

    emis_subject_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[dict[str, Any]] = mapped_column(JSONB)
    short_name: Mapped[str | None] = mapped_column(String(64))
    can_be_divided: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
