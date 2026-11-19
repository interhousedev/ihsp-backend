"""ORM of essay review links and feedback; text columns hold ciphertext."""

from datetime import datetime
from uuid import UUID

from app.modules.admission.domain.essay_invites import AUDIENCES
from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["EssayFeedbackRow", "EssayInviteRow"]


class EssayInviteRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A review link; only the SHA-256 of its token is stored."""

    __tablename__ = "essay_invites"
    __table_args__ = (check_in("audience", AUDIENCES), S)

    essay_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.essays.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[bytes | None] = mapped_column(LargeBinary)
    audience: Mapped[str] = mapped_column(String(20))
    can_comment: Mapped[bool] = mapped_column(Boolean)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EssayFeedbackRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A comment on an essay; no invite means the student's own note or reply."""

    __tablename__ = "essay_feedback"
    __table_args__ = (check_in("audience", AUDIENCES), S)

    essay_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.essays.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    invite_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.essay_invites.id", ondelete="SET NULL"), index=True
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.essay_feedback.id", ondelete="CASCADE"), index=True
    )
    quote: Mapped[bytes | None] = mapped_column(LargeBinary)
    anchor_start: Mapped[int | None] = mapped_column(Integer)
    anchor_end: Mapped[int | None] = mapped_column(Integer)
    body: Mapped[bytes] = mapped_column(LargeBinary)
    author_name: Mapped[bytes] = mapped_column(LargeBinary)
    audience: Mapped[str | None] = mapped_column(String(20))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
