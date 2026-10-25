"""ORM model of academic.results."""

from decimal import Decimal
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class Result(IdMixin, TimestampMixin, Base):
    """Current semester mark of a subject, or the semester GPA (no subject)."""

    __tablename__ = "results"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "semester",
            "subject_id",
            name="uq_results_student_semester_subject",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("emis_rating BETWEEN 0 AND 100", name="emis_rating"),
        {"schema": "academic"},
    )

    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.students.user_id")
    )
    semester: Mapped[int] = mapped_column(SmallInteger)
    subject_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("academic.subjects.id")
    )
    value: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    lesson_avg: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    midterm_avg: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    final_avg: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    emis_rating: Mapped[int | None] = mapped_column(SmallInteger)
    marks_count: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    emis_hash: Mapped[str | None] = mapped_column(String(128))
