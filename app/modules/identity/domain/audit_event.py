"""Audit event record (read side) and the event type names."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

LOGIN_SUCCESS = "login.success"
LOGIN_FAILED = "login.failed"
LOGOUT = "logout"
PASSWORD_CHANGED = "password.changed"
PASSWORD_RESET = "password.reset"
OTP_ENABLED = "otp.enabled"
OTP_DISABLED = "otp.disabled"
OTP_RESET_REQUESTED = "otp.reset_requested"
OTP_RESET_CANCELLED = "otp.reset_cancelled"
OTP_RESET_APPLIED = "otp.reset_applied"
OTP_RESET_BY_ADMIN = "otp.reset_by_admin"
EMAIL_CHANGED = "email.changed"
TELEGRAM_LINKED = "telegram.linked"
TELEGRAM_UNLINKED = "telegram.unlinked"
SESSION_REVOKED = "session.revoked"
SESSIONS_REVOKED = "sessions.revoked"
CONNECTOR_CREATED = "connector.created"
CONNECTOR_REVOKED = "connector.revoked"
ROLE_GRANTED = "role.granted"
ROLE_REVOKED = "role.revoked"
USER_BLOCKED = "user.blocked"
USER_UNBLOCKED = "user.unblocked"
USER_CREATED = "user.created"
USER_UPDATED = "user.updated"
USER_DEACTIVATED = "user.deactivated"
USER_ACTIVATED = "user.activated"
USER_PURGED = "user.purged"
STUDENT_VIEWED = "student.viewed"
PASSWORD_RESET_BY_ADMIN = "password.reset_by_admin"
MAIL_SUSPENDED = "mail.suspended"
MAIL_RESUMED = "mail.resumed"
OAUTH_CLIENT_VERIFIED = "oauth_client.verified"


@dataclass(frozen=True, slots=True)
class AuditEventRecord:
    """A stored audit event."""

    id: UUID
    type: str
    created_at: datetime
    user_id: UUID | None = None
    actor_id: UUID | None = None
    ip: str | None = None
    user_agent: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
