"""ORM models of the Coach: sessions and their turns."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column


class TutorSession(IdMixin, TimestampMixin, Base):
    """A tutoring conversation of one learner on one step."""

    __tablename__ = "tutor_sessions"
    __table_args__ = (
        CheckConstraint("mode IN ('ask', 'hint', 'remediate', 'recap')", name="mode"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('resolved', 'abandoned', 'escalated')",
            name="outcome",
        ),
        CheckConstraint("hint_level BETWEEN 0 AND 3", name="hint_level"),
        Index("ix_tutor_sessions_user_id_step_id", "user_id", "step_id"),
        Index("ix_tutor_sessions_step_id_opened_at", "step_id", "opened_at"),
        {"schema": "lms"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    enrollment_id: Mapped[UUID | None] = mapped_column(Uuid)
    step_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.course_steps.id", ondelete="CASCADE")
    )
    block_id: Mapped[str | None] = mapped_column(String(64))
    revision_id: Mapped[UUID | None] = mapped_column(Uuid)
    mode: Mapped[str] = mapped_column(String(16))
    hint_level: Mapped[int] = mapped_column(SmallInteger, server_default=sql_text("0"))
    outcome: Mapped[str | None] = mapped_column(String(16))
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TutorTurn(IdMixin, TimestampMixin, Base):
    """One message of a session."""

    __tablename__ = "tutor_turns"
    __table_args__ = (
        CheckConstraint("role IN ('learner', 'tutor')", name="role"),
        Index("ix_tutor_turns_session_id_created_at", "session_id", "created_at"),
        {"schema": "lms"},
    )

    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.tutor_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    hint_level: Mapped[int] = mapped_column(SmallInteger, server_default=sql_text("0"))
    citations: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default=sql_text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
