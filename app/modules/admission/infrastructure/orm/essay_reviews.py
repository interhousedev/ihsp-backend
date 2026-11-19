"""Stored essay reviews: coach checks, base and university reviews (sealed)."""

from uuid import UUID

from app.modules.admission.domain.essay_reviews import REVIEW_KINDS
from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import ForeignKey, Index, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class EssayReviewRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """One review result; `result` is the sealed JSON of the review."""

    __tablename__ = "essay_reviews"
    __table_args__ = (
        check_in("kind", REVIEW_KINDS),
        Index(
            "uq_essay_reviews_input",
            "essay_id",
            "kind",
            "institution_id",
            "input_digest",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_essay_reviews_latest", "essay_id", "kind", "created_at"),
        Index("ix_essay_reviews_student_id", "student_id"),
        S,
    )

    essay_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.essays.id", ondelete="CASCADE")
    )
    student_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(8))
    institution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.institutions.id", ondelete="CASCADE")
    )
    input_digest: Mapped[str] = mapped_column(String(64))
    result: Mapped[bytes] = mapped_column(LargeBinary)
    model: Mapped[str] = mapped_column(String(200))
    prompt_ref: Mapped[str] = mapped_column(String(200))
