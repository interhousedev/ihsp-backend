"""Response models shared by the identity routes (API contract → Schemas)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.modules.identity.application.list_sessions import SessionView
from app.modules.identity.domain.audit_event import AuditEventRecord
from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.domain.user import User

from pydantic import BaseModel

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class PersonRefResponse(BaseModel):
    """PersonRef = {id, first_name, last_name}."""

    id: UUID
    first_name: str
    last_name: str

    @classmethod
    def of(cls, user: User) -> "PersonRefResponse":
        """Map a user."""
        return cls(id=user.id, first_name=user.first_name, last_name=user.last_name)


class TelegramAccountResponse(BaseModel):
    """TelegramAccount."""

    telegram_user_id: int
    username: str | None
    otp_delivery: bool
    blocked: bool
    linked_at: datetime

    @classmethod
    def of(cls, link: TelegramLink) -> "TelegramAccountResponse":
        """Map a link."""
        return cls(
            telegram_user_id=link.telegram_user_id,
            username=link.username,
            otp_delivery=link.otp_delivery,
            blocked=link.blocked_at is not None,
            linked_at=link.linked_at or EPOCH,
        )


class SessionItemResponse(BaseModel):
    """SessionItem."""

    id: UUID
    ip: str | None
    user_agent: str | None
    amr: list[str]
    last_seen_at: datetime
    current: bool

    @classmethod
    def of(cls, view: SessionView) -> "SessionItemResponse":
        """Map a session view."""
        session = view.session
        return cls(
            id=session.id,
            ip=session.ip,
            user_agent=session.user_agent or None,
            amr=session.amr,
            last_seen_at=session.last_seen_at,
            current=view.current,
        )


class AuditItemResponse(BaseModel):
    """AuditItem."""

    id: UUID
    type: str
    ip: str | None
    user_agent: str | None
    actor: PersonRefResponse | None
    created_at: datetime
    metadata: dict[str, Any]

    @classmethod
    def of(
        cls, event: AuditEventRecord, actors: dict[UUID, User]
    ) -> "AuditItemResponse":
        """Map an event, naming the actor if known."""
        actor = actors.get(event.actor_id) if event.actor_id else None
        return cls(
            id=event.id,
            type=event.type,
            ip=event.ip,
            user_agent=event.user_agent,
            actor=PersonRefResponse.of(actor) if actor else None,
            created_at=event.created_at,
            metadata=event.metadata,
        )
