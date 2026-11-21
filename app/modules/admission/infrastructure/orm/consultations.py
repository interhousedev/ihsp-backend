"""Consultation requests, quiz answers and profile interests."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    LockMixin,
    S,
    UpdatedMixin,
    check_in,
    max_len,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ConsultationRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A student's request for a conversation with a counselor or a mentor."""

    __tablename__ = "consultations"
    __table_args__ = (
        check_in("with_kind", ("counselor", "mentor")),
        check_in(
            "linked_kind", ("project", "essay", "activity", "application", "other")
        ),
        check_in("format", ("online", "offline")),
        check_in(
            "status",
            ("requested", "proposed", "accepted", "declined", "completed", "cancelled"),
        ),
        CheckConstraint("cardinality(preferred_times) <= 5", name="times_count"),
        max_len("topic", 200),
        max_len("details", 1000),
        max_len("location", 200),
        max_len("staff_notes", 2000),
        max_len("decline_reason", 1000),
        Index("ix_consultations_student", "student_id", "created_at"),
        Index("ix_consultations_queue", "with_kind", "status"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid)
    with_kind: Mapped[str] = mapped_column(String(10))
    topic: Mapped[str] = mapped_column(String(200))
    details: Mapped[str] = mapped_column(String(1000), server_default="")
    linked_kind: Mapped[str] = mapped_column(String(12), server_default="other")
    linked_id: Mapped[UUID | None] = mapped_column(Uuid)
    preferred_times: Mapped[list[datetime]] = mapped_column(
        ARRAY(DateTime(timezone=True)), server_default=text("'{}'")
    )
    format: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(10), server_default="requested")
    staff_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str] = mapped_column(String(200), server_default="")
    staff_notes: Mapped[str] = mapped_column(String(2000), server_default="")
    decline_reason: Mapped[str] = mapped_column(String(1000), server_default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuizAnswersRow(CreatedMixin, UpdatedMixin, Base):
    """The stored answers of one quiz of a student."""

    __tablename__ = "quiz_answers"
    __table_args__ = (check_in("quiz", ("career", "algorithm", "budget")), S)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    quiz: Mapped[str] = mapped_column(String(12), primary_key=True)
    answers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    completed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class ProfileDetailsRow(CreatedMixin, UpdatedMixin, Base):
    """Fields of interest and service interests of a student."""

    __tablename__ = "profile_details"
    __table_args__ = (
        CheckConstraint("cardinality(interest_fields) <= 19", name="interests_count"),
        CheckConstraint("cardinality(service_interests) <= 8", name="services_count"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    interest_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
    service_interests: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
