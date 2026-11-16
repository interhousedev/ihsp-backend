"""ORM of career exploration: inventory questions, majors, plans."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admission.domain.career import AREA_MAX, CODE_MAX, SECTIONS
from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    LockMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import Boolean, DateTime, Integer, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["CareerMajorRow", "CareerPlanRow", "CareerQuestionRow"]


class CareerQuestionRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """An inventory question; `prompt` holds the text per locale."""

    __tablename__ = "career_questions"
    __table_args__ = (check_in("section", SECTIONS), S)

    section: Mapped[str] = mapped_column(String(16))
    prompt: Mapped[dict[str, str]] = mapped_column(JSONB)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class CareerMajorRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A major of the taxonomy; `name` holds the text per locale."""

    __tablename__ = "career_majors"
    __table_args__ = (S,)

    code: Mapped[str] = mapped_column(String(CODE_MAX), unique=True)
    area: Mapped[str] = mapped_column(String(AREA_MAX))
    name: Mapped[dict[str, str]] = mapped_column(JSONB)
    minor_ok: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class CareerPlanRow(CreatedMixin, UpdatedMixin, LockMixin, Base):
    """One student's answers, professions, choice and spike."""

    __tablename__ = "career_plans"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    answers: Mapped[dict[str, str]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    professions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    majors: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    minors: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    fit: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    spike: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    spike_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
