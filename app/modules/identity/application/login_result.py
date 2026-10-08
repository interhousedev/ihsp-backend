"""Result types shared by the login use cases."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SecondFactor:
    """A code was sent; the client must send it back with this ticket."""

    ticket: str
    channels: list[str] = field(default_factory=list)
    method: str = "otp"


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Either the URL to continue at, or a second factor to complete."""

    redirect_to: str | None = None
    second_factor: SecondFactor | None = None
