"""Port: brute-force protection for logins and passwordless OTP."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FailureCounts:
    """Failed password attempts seen so far."""

    for_login_and_ip: int
    for_account: int


class LoginThrottle(Protocol):
    """Exponential back-off per (login, IP) and failure counters (ID-15)."""

    async def check(self, login: str, ip: str) -> None:
        """Raise AccountLockedError while the (login, IP) pair is locked."""
        ...

    async def record_failure(
        self, login: str, ip: str, user_id: UUID | None
    ) -> FailureCounts:
        """Count a failed password and lock the pair after 5 failures."""
        ...

    async def reset(self, login: str, ip: str) -> None:
        """Forget failures of the pair after a successful login."""
        ...

    async def otp_failures(self, user_id: UUID, ip: str) -> int:
        """Failed passwordless OTP codes today for the account and IP."""
        ...

    async def record_otp_failure(self, user_id: UUID, ip: str) -> int:
        """Count a wrong passwordless OTP code."""
        ...
