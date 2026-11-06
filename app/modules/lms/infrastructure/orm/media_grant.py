"""ORM model of lms.media_grants."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class MediaGrant(IdMixin, TimestampMixin, Base):
    """A revocable media link; one row per (user, step, block), so rows stay bounded."""

    __tablename__ = "media_grants"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_media_grants_token_hash"),
        UniqueConstraint(
            "issued_to", "step_id", "block_id", name="uq_media_grants_issued_block"
        ),
        {"schema": "lms"},
    )

    token_hash: Mapped[str] = mapped_column(String(64))
    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE")
    )
    step_id: Mapped[UUID] = mapped_column(Uuid)
    block_id: Mapped[str] = mapped_column(String(100))
    file_id: Mapped[UUID] = mapped_column(Uuid)
    issued_to: Mapped[UUID] = mapped_column(Uuid)
    connector_id: Mapped[UUID | None] = mapped_column(Uuid)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeem_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
