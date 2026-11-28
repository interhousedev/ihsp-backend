"""The opportunities catalog, its taxonomy, submissions and student plans."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    LockMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

_KINDS = (
    "exam",
    "certification",
    "course",
    "event",
    "recurring",
    "program",
    "scholarship",
    "research",
)


class OpportunityTaxonomyRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A field, subfield or subject (names by locale)."""

    __tablename__ = "opportunity_taxonomy"
    __table_args__ = (check_in("level", ("field", "subfield", "subject")), S)

    level: Mapped[str] = mapped_column(String(10))
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.opportunity_taxonomy.id", ondelete="CASCADE"),
        index=True,
    )
    names: Mapped[dict[str, str]] = mapped_column(JSONB)
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class OpportunityRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A published entry; the approved draft is the payload."""

    __tablename__ = "opportunities"
    __table_args__ = (check_in("kind", _KINDS), S)

    kind: Mapped[str] = mapped_column(String(14))
    title: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    subject_ids: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    archived: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    audience: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[\"admission\"]'::jsonb")
    )


class OpportunitySubmissionRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A proposed new entry or edit, waiting for moderation."""

    __tablename__ = "opportunity_submissions"
    __table_args__ = (
        check_in("status", ("pending", "approved", "rejected")),
        check_in("submitter_role", ("student", "staff", "helper", "admin")),
        Index("ix_opportunity_submissions_status", "status", "created_at"),
        S,
    )

    target_id: Mapped[UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(10), server_default="pending")
    submitted_by: Mapped[UUID] = mapped_column(Uuid, index=True)
    submitter_role: Mapped[str] = mapped_column(String(10))
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(500))
    applied_id: Mapped[UUID | None] = mapped_column(Uuid)


class OpportunityPlanEntryRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """An entry a student saved to their plan."""

    __tablename__ = "opportunity_plan_entries"
    __table_args__ = (
        UniqueConstraint("student_id", "opportunity_id"),
        CheckConstraint("planned_grade BETWEEN 1 AND 12", name="planned_grade"),
        CheckConstraint(
            "planned_term IN ('fall', 'spring', 'summer')", name="planned_term"
        ),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    opportunity_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.opportunities.id", ondelete="CASCADE")
    )
    planned_grade: Mapped[int | None] = mapped_column(SmallInteger)
    planned_term: Mapped[str | None] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(String(500))


class OpportunityAiPlanRow(UpdatedMixin, Base):
    """The last generated plan of a student."""

    __tablename__ = "opportunity_ai_plans"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = [
    "OpportunityAiPlanRow",
    "OpportunityPlanEntryRow",
    "OpportunityRow",
    "OpportunitySubmissionRow",
    "OpportunityTaxonomyRow",
]
