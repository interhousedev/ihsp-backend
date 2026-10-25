"""Port: short-lived one-time codes."""

from typing import Protocol


class OtpStore(Protocol):
    """Issues and checks 6-digit codes (ID-14): 5 minutes, 3 attempts, 60 s cooldown."""

    async def issue(
        self,
        purpose: str,
        subject_key: str,
        *,
        ttl: int = 300,
        cooldown: int | None = 60,
    ) -> str:
        """Create a code, replacing an older one.

        Raises:
            RateLimitedError: a code was issued less than ``cooldown`` seconds ago.
        """
        ...

    async def verify(self, purpose: str, subject_key: str, code: str) -> bool:
        """Check a code; every call costs one attempt; success consumes the code."""
        ...

    async def attempts_left(self, purpose: str, subject_key: str) -> int:
        """Attempts remaining for the current code (0 if none)."""
        ...

    async def discard(self, purpose: str, subject_key: str) -> None:
        """Drop the code."""
        ...
