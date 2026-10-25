"""ORM models of academic.group_curriculum and academic.group_curriculum_subject."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class GroupCurriculum(TimestampMixin, Base):
    """The EMIS curriculum of a group: header, semester dates and totals.

    ``speciality`` is ``{"uz", "ru", "en"}`` and ``direction`` is ``{"emis_id",
    "name", "code"}``; ``semester_dates`` lists ``{"number", "starts_on", "ends_on"}``;
    ``subject_totals`` lists ``{"emis_subject_id", "name", "subject_type_id",
    "study_hours"}``; ``exams`` and ``vocational`` list ``{"emis_id", "name",
    "study_hours"}``.
    """

    __tablename__ = "group_curriculum"
    __table_args__ = {"schema": "academic"}

    group_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.groups.id", ondelete="CASCADE"), primary_key=True
    )
    emis_curriculum_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    speciality: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    direction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    edu_form: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(8))
    rating_min: Mapped[int | None] = mapped_column(SmallInteger)
    rating_max: Mapped[int | None] = mapped_column(SmallInteger)
    semesters_count: Mapped[int | None] = mapped_column(SmallInteger)
    semester_dates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    subject_totals: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    exams: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    vocational: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class GroupCurriculumSubject(TimestampMixin, Base):
    """A subject of one semester of a group's curriculum (names as EMIS sent them).

    The link to ``academic.subjects`` is by ``emis_subject_id``, with no foreign key:
    the subject row may not exist yet.
    """

    __tablename__ = "group_curriculum_subject"
    __table_args__ = (
        Index("ix_group_curriculum_subject_group_id", "group_id"),
        {"schema": "academic"},
    )

    group_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.groups.id", ondelete="CASCADE"), primary_key=True
    )
    semester_number: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    emis_subject_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[dict[str, Any]] = mapped_column(JSONB)
    subject_type_id: Mapped[int | None] = mapped_column(SmallInteger)
    study_hours: Mapped[int | None] = mapped_column(Integer)
    class_hours: Mapped[int | None] = mapped_column(Integer)
    independent_hours: Mapped[int | None] = mapped_column(Integer)
    is_separated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
