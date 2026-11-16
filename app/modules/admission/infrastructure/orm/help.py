"""Help requests and guest links (§3.3)."""

from datetime import datetime
from uuid import UUID

from app.modules.admission.domain.workflow import HELP_TRANSITIONS
from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    LockMixin,
    S,
    UpdatedMixin,
    check_in,
    max_len,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column


class HelpRequestRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A student's help request; `item_id` null is a general request."""

    __tablename__ = "help_requests"
    __table_args__ = (
        check_in("kind", ("website", "design", "proof", "other")),
        check_in("status", tuple(HELP_TRANSITIONS)),
        max_len("brief", 1000),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.items.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(8))
    brief: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="open")
    helper_user_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    expires_at: Mapped[datetime]


class HelpResponseRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A helper's (or guest's) response."""

    __tablename__ = "help_responses"
    __table_args__ = (max_len("text", 2000), S)

    help_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.help_requests.id", ondelete="CASCADE"), index=True
    )
    author_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    guest_link_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.guest_links.id", ondelete="SET NULL")
    )
    text: Mapped[str] = mapped_column(Text, server_default="")
    url: Mapped[str | None] = mapped_column(String(2000))
    file_id: Mapped[UUID | None] = mapped_column(Uuid)


class GuestLinkRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A hashed-token guest link; caps: 60 days, 20 sessions."""

    __tablename__ = "guest_links"
    __table_args__ = (
        CheckConstraint(
            "scope <@ ARRAY['activities:read', 'help:respond']::text[]", name="scope"
        ),
        CheckConstraint("max_sessions BETWEEN 1 AND 20", name="max_sessions"),
        CheckConstraint(
            "expires_at <= created_at + interval '60 days'", name="expires_at"
        ),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    help_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.help_requests.id", ondelete="CASCADE")
    )
    scope: Mapped[list[str]] = mapped_column(ARRAY(Text))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_prefix: Mapped[str] = mapped_column(String(8))
    label: Mapped[str | None] = mapped_column(String(60))
    expires_at: Mapped[datetime]
    max_sessions: Mapped[int] = mapped_column(Integer, server_default=text("5"))
    sessions_used: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[str | None] = mapped_column(String(40))
    rotated_from: Mapped[UUID | None] = mapped_column(Uuid)
    claimed_by: Mapped[UUID | None] = mapped_column(Uuid)
    claimed_at: Mapped[datetime | None]


class GuestSessionRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A guest browser session opened from a link (≤2 h)."""

    __tablename__ = "guest_sessions"
    __table_args__ = (S,)

    guest_link_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.guest_links.id", ondelete="CASCADE"), index=True
    )
    session_hash: Mapped[str] = mapped_column(String(64), unique=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime]
