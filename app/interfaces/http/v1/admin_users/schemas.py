"""Response models shared by the Administration user routes."""

from datetime import datetime
from uuid import UUID

from app.interfaces.http.v1.id.schemas import (
    AuditItemResponse,
    SessionItemResponse,
    TelegramAccountResponse,
)
from app.modules.identity.application.get_user_detail import UserDetail
from app.modules.identity.application.list_sessions import SessionView
from app.modules.identity.domain.user import User
from app.shared.actor import Role

from pydantic import BaseModel


class AdminUserResponse(BaseModel):
    """AdminUser."""

    id: UUID
    login: str | None
    first_name: str
    last_name: str
    middle_name: str | None
    roles: list[Role]
    status: str
    emis_status: str | None
    recovery_email: str | None
    mail_suspended: bool
    password_change_required: bool = False
    photo_url: str | None = None
    created_at: datetime | None
    last_login_at: datetime | None

    @classmethod
    def of(cls, user: User, photo_url: str | None = None) -> "AdminUserResponse":
        """Map a user; ``photo_url`` is the short-lived link to their photo."""
        return cls(
            id=user.id,
            login=user.login,
            first_name=user.first_name,
            last_name=user.last_name,
            middle_name=user.middle_name,
            roles=sorted(user.roles, key=lambda role: role.value),
            status=user.status.value,
            emis_status=user.emis_status,
            recovery_email=user.recovery_email,
            mail_suspended=user.mail_suspended_at is not None,
            password_change_required=user.password_change_required,
            photo_url=photo_url,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )


class AdminUserDetailResponse(AdminUserResponse):
    """AdminUserDetail = AdminUser + Telegram, sessions and recent audit."""

    telegram: list[TelegramAccountResponse]
    sessions: list[SessionItemResponse]
    recent_audit: list[AuditItemResponse]
    mailbox: str | None = None

    @classmethod
    def detail(
        cls, detail: UserDetail, photo_url: str | None = None
    ) -> "AdminUserDetailResponse":
        """Map the detail view."""
        base = AdminUserResponse.of(detail.user, photo_url)
        return cls(
            **base.model_dump(),
            mailbox=detail.mailbox,
            telegram=[TelegramAccountResponse.of(link) for link in detail.telegram],
            sessions=[
                SessionItemResponse.of(SessionView(session, current=False))
                for session in detail.sessions
            ],
            recent_audit=[
                AuditItemResponse.of(event, detail.actors)
                for event in detail.recent_audit
            ],
        )
