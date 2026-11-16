"""Searchable chunks of one student's data (words index; vectors live in `vectors`)."""

from datetime import datetime
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import CreatedMixin, S
from app.shared.db.base import Base

from sqlalchemy import (
    CHAR,
    Computed,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column


class StudentChunkRow(CreatedMixin, Base):
    """One piece of a student's row; `content_hash` keys `vectors.embeddings`."""

    __tablename__ = "admission_student_chunks"
    __table_args__ = (
        Index("ix_admission_student_chunks_tsv", "tsv", postgresql_using="gin"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    ref_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', title || ' ' || body)", persisted=True),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
