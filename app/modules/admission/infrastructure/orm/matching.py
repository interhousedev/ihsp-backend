"""Preference answers and university swipe decisions of a student."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class StudentPreferenceRow(CreatedMixin, UpdatedMixin, Base):
    """The answers of one student."""

    __tablename__ = "student_preferences"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    answers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )


class DecisionRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A student's swipe on a university."""

    __tablename__ = "university_decisions"
    __table_args__ = (
        check_in("decision", ("interested", "not_my_vibe")),
        UniqueConstraint(
            "student_id",
            "institution_id",
            name="uq_university_decisions_student_institution",
        ),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.institutions.id", ondelete="CASCADE")
    )
    decision: Mapped[str] = mapped_column(String(12))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_list_entry: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
