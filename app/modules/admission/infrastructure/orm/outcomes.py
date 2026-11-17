"""Self-reported application outcomes."""

from uuid import UUID

from app.modules.admission.domain.outcomes import (
    MAX_CYCLE,
    MIN_CYCLE,
    OUTCOME_PLANS,
    OUTCOME_STATUSES,
)
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
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class ApplicationOutcomeRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A student's report for one institution and cycle."""

    __tablename__ = "application_outcomes"
    __table_args__ = (
        check_in("status", OUTCOME_STATUSES),
        check_in("plan", OUTCOME_PLANS),
        CheckConstraint(
            f"cycle BETWEEN {MIN_CYCLE} AND {MAX_CYCLE}", name="cycle_range"
        ),
        UniqueConstraint(
            "student_id",
            "institution_id",
            "cycle",
            name="uq_application_outcomes_student_institution_cycle",
        ),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.institutions.id", ondelete="CASCADE"), index=True
    )
    cycle: Mapped[int] = mapped_column(Integer)
    plan: Mapped[str] = mapped_column(String(8), server_default="rd")
    status: Mapped[str] = mapped_column(String(10), server_default="applied")
    share_name: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
