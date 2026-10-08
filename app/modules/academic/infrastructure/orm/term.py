"""ORM model of academic.terms."""

from datetime import date
from typing import Any

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column


class Term(IdMixin, TimestampMixin, Base):
    """A half of an academic year with its bell schedule and non-study days."""

    __tablename__ = "terms"
    __table_args__ = (
        UniqueConstraint("academic_year", "half", name="uq_terms_academic_year_half"),
        CheckConstraint("half IN (1, 2)", name="half"),
        CheckConstraint("ends_on >= starts_on", name="dates"),
        ExcludeConstraint(
            (func.daterange(text("starts_on"), text("ends_on"), "[]"), "&&"),
            name="ex_terms_no_overlap",
            using="gist",
        ),
        {"schema": "academic"},
    )

    academic_year: Mapped[str] = mapped_column(String(16))
    half: Mapped[int] = mapped_column(SmallInteger)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    non_study_days: Mapped[list[date]] = mapped_column(
        ARRAY(Date), server_default=text("'{}'")
    )
    moved_days: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    bells: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
