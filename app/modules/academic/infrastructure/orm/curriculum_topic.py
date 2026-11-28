"""ORM model of academic.curriculum_topics."""

from datetime import datetime

from app.shared.db.base import Base

from sqlalchemy import DateTime, Index, Integer, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column


class CurriculumTopic(Base):
    """A topic of an EMIS subject's thematic plan (the question bank's catalogue)."""

    __tablename__ = "curriculum_topics"
    __table_args__ = (
        Index("ix_curriculum_topics_emis_subject_id", "emis_subject_id"),
        {"schema": "academic"},
    )

    emis_subject_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    semester: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    topic: Mapped[str] = mapped_column(String(255), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
