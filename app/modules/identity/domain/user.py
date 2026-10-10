"""The User entity and its status rules."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from app.modules.identity.domain.errors import InvalidStatusError
from app.shared.actor import Role
from app.shared.contracts.identity import UserRef, UserStatus


class ActivationPurpose(StrEnum):
    """Why an activation token exists."""

    ACTIVATE = "activate"
    RESET_PASSWORD = "reset_password"


@dataclass(slots=True)
class User:
    """A person with an ID Service account."""

    id: UUID
    first_name: str
    last_name: str
    middle_name: str | None = None
    login: str | None = None
    password_hash: str | None = None
    password_change_required: bool = False
    roles: set[Role] = field(default_factory=set)
    recovery_email: str | None = None
    recovery_email_verified_at: datetime | None = None
    otp_enabled: bool = False
    otp_via_email: bool = False
    status: UserStatus = UserStatus.ACTIVE
    auth_epoch: int = 0
    activation_token_hash: str | None = None
    activation_expires_at: datetime | None = None
    activation_purpose: ActivationPurpose | None = None
    emis_student_id: int | None = None
    emis_teacher_id: int | None = None
    emis_vault_ref: UUID | None = None
    emis_status: Literal["active", "needs_reauth"] | None = None
    mail_suspended_at: datetime | None = None
    preferences: dict[str, Any] = field(default_factory=dict)
    last_login_at: datetime | None = None
    otp_reset_effective_at: datetime | None = None
    otp_reset_request_id: UUID | None = None
    deleted_at: datetime | None = None
    created_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        """True when the user may sign in."""
        return self.status == UserStatus.ACTIVE

    @property
    def is_admin(self) -> bool:
        """True for the Administration role."""
        return Role.ADMIN in self.roles

    @property
    def locale(self) -> str:
        """Preferred locale with the default."""
        value = self.preferences.get("locale")
        return value if isinstance(value, str) else "ru"

    @property
    def has_verified_email(self) -> bool:
        """True when the recovery email is confirmed."""
        return self.recovery_email is not None and (
            self.recovery_email_verified_at is not None
        )

    @property
    def full_name(self) -> str:
        """Last name and first name."""
        return f"{self.last_name} {self.first_name}".strip()

    def bump_epoch(self) -> None:
        """Invalidate every access token issued so far."""
        self.auth_epoch += 1

    def block(self) -> None:
        """Block an active account and log it out everywhere."""
        if self.status != UserStatus.ACTIVE:
            raise InvalidStatusError(params={"status": self.status.value})
        self.status = UserStatus.BLOCKED
        self.bump_epoch()

    def unblock(self) -> None:
        """Restore a blocked account (sessions must be created again)."""
        if self.status != UserStatus.BLOCKED:
            raise InvalidStatusError(params={"status": self.status.value})
        self.status = UserStatus.ACTIVE
        self.bump_epoch()

    def deactivate(self) -> None:
        """Mark a former staff member as deactivated."""
        if self.status in (UserStatus.DELETED, UserStatus.DEACTIVATED):
            raise InvalidStatusError(params={"status": self.status.value})
        self.status = UserStatus.DEACTIVATED
        self.bump_epoch()

    def grant(self, role: Role) -> bool:
        """Add a role; return True if it was new."""
        if role in self.roles:
            return False
        self.roles.add(role)
        self.bump_epoch()
        return True

    def revoke(self, role: Role) -> bool:
        """Remove a role; return True if it was held."""
        if role not in self.roles:
            return False
        self.roles.discard(role)
        self.bump_epoch()
        return True

    def set_activation(
        self, token_hash: str, expires_at: datetime, purpose: ActivationPurpose
    ) -> None:
        """Store a one-time activation or reset link (hash only)."""
        self.activation_token_hash = token_hash
        self.activation_expires_at = expires_at
        self.activation_purpose = purpose

    def clear_activation(self) -> None:
        """Forget the activation link after use."""
        self.activation_token_hash = None
        self.activation_expires_at = None
        self.activation_purpose = None

    def clear_otp_reset(self) -> None:
        """Forget a pending OTP reset."""
        self.otp_reset_effective_at = None
        self.otp_reset_request_id = None

    def to_ref(self) -> UserRef:
        """Read-only view for other modules."""
        return UserRef(
            id=self.id,
            login=self.login,
            first_name=self.first_name,
            last_name=self.last_name,
            middle_name=self.middle_name,
            roles=frozenset(self.roles),
            status=self.status,
            locale=self.locale,
            emis_status=self.emis_status,
        )
