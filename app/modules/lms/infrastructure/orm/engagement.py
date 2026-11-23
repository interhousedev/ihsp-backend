"""ORM models of the engagement tables (XP, profiles, review, mastery, quests)."""

from datetime import date, datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class XpEvent(IdMixin, TimestampMixin, Base):
    """One XP award; the single source of XP and levels on every platform."""

    __tablename__ = "xp_events"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source", "ref", name="uq_xp_events_user_source_ref"
        ),
        CheckConstraint(
            "source IN ('step', 'test', 'review', 'quest', 'exam', 'widget')",
            name="source",
        ),
        CheckConstraint("xp >= 0", name="xp_non_negative"),
        Index("ix_xp_events_user_id_earned_on", "user_id", "earned_on"),
        Index("ix_xp_events_course_id_earned_on", "course_id", "earned_on"),
        {"schema": "lms"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    course_id: Mapped[UUID | None] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(String(16))
    ref: Mapped[str] = mapped_column(String(128))
    xp: Mapped[int] = mapped_column(Integer)
    earned_on: Mapped[date] = mapped_column(Date)


class EngagementProfile(TimestampMixin, Base):
    """A learner's weekly goal and the XP sync watermark."""

    __tablename__ = "engagement_profiles"
    __table_args__ = (
        CheckConstraint("weekly_goal_days BETWEEN 1 AND 7", name="weekly_goal_days"),
        {"schema": "lms"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    weekly_goal_days: Mapped[int] = mapped_column(Integer, server_default=text("5"))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewItem(IdMixin, TimestampMixin, Base):
    """FSRS state of a test question the learner missed."""

    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "step_id",
            "block_id",
            "question_id",
            name="uq_review_items_user_question",
        ),
        Index("ix_review_items_user_id_due_at", "user_id", "due_at"),
        {"schema": "lms"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE")
    )
    step_id: Mapped[UUID] = mapped_column(Uuid)
    revision_id: Mapped[UUID] = mapped_column(Uuid)
    block_id: Mapped[str] = mapped_column(String(64))
    question_id: Mapped[str] = mapped_column(String(64))
    stability: Mapped[float] = mapped_column(Float)
    difficulty: Mapped[float] = mapped_column(Float)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reps: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    lapses: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class CourseEngagementSettings(TimestampMixin, Base):
    """Per-course engagement options (the mastery unlock threshold)."""

    __tablename__ = "course_engagement_settings"
    __table_args__ = (
        CheckConstraint(
            "unlock_threshold_pct BETWEEN 1 AND 100", name="unlock_threshold_pct"
        ),
        {"schema": "lms"},
    )

    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE"), primary_key=True
    )
    unlock_threshold_pct: Mapped[int | None] = mapped_column(Integer)


class ClassQuest(IdMixin, Base):
    """A class-wide goal set by course staff for a date range."""

    __tablename__ = "class_quests"
    __table_args__ = (
        CheckConstraint(
            "goal_kind IN ('steps', 'xp', 'review_days')", name="goal_kind"
        ),
        CheckConstraint("target > 0 AND class_target > 0", name="targets_positive"),
        CheckConstraint("ends_on >= starts_on", name="dates_ordered"),
        Index("ix_class_quests_course_id_ends_on", "course_id", "ends_on"),
        {"schema": "lms"},
    )

    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(200))
    goal_kind: Mapped[str] = mapped_column(String(16))
    target: Mapped[int] = mapped_column(Integer)
    class_target: Mapped[int] = mapped_column(Integer)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
