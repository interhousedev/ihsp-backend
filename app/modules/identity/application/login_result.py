"""Result types shared by the login use cases."""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, slots=True)
class SecondFactor:
    """A code was sent; the client must send it back with this ticket."""

    ticket: str
    channels: list[str] = field(default_factory=list)
    method: str = "otp"


@dataclass(frozen=True, slots=True)
class PasswordChange:
    """The password was set by an administrator; the client must choose a new one."""

    ticket: str


@dataclass(frozen=True, slots=True)
class AccountRestore:
    """The account is scheduled for deletion: restore it (or not) with the ticket."""

    ticket: str
    deletes_on: date


@dataclass(frozen=True, slots=True)
class LoginResult:
    """The URL to continue at, a second factor, a password change or a restore."""

    redirect_to: str | None = None
    second_factor: SecondFactor | None = None
    password_change: PasswordChange | None = None
    restore: AccountRestore | None = None
