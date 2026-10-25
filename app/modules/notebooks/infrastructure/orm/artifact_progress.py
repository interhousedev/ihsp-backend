"""ORM model of notebooks.artifact_progress."""

from typing import Any
from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import ForeignKey, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ArtifactProgress(TimestampMixin, Base):
    """A student's progress in a flash card deck or quiz (resume where they left)."""

    __tablename__ = "artifact_progress"
    __table_args__ = ({"schema": "notebooks"},)

    artifact_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("notebooks.artifacts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB)
