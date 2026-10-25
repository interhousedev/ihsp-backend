"""A login session (one browser, one mini app launch)."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

ADMIN_MFA_WINDOW = timedelta(hours=12)
SESSION_LIFETIME = timedelta(days=30)
UNKNOWN_IP = (
    "0.0.0.0"  # nosec B104 -- sentinel for an unknown client, not a bind address
)


@dataclass(slots=True)
class LoginSession:
    """One login of a user, as accepted by the login app."""

    id: UUID
    user_id: UUID
    ip: str
    user_agent: str
    expires_at: datetime
    last_seen_at: datetime
    hydra_sid: str | None = None
    amr: list[str] = field(default_factory=list)
    mfa_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        """True while the session is neither revoked nor expired."""
        return self.revoked_at is None and self.expires_at > now

    def mfa_is_fresh(self, now: datetime) -> bool:
        """True when password + OTP happened within the admin window."""
        return self.mfa_at is not None and now - self.mfa_at <= ADMIN_MFA_WINDOW
