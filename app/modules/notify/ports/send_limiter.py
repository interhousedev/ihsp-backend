"""Port that paces outgoing Telegram messages."""

from typing import Protocol


class SendLimiter(Protocol):
    """Waits until one more message may be sent without breaking Telegram limits."""

    async def acquire(self) -> None:
        """Return when the caller may send one message."""
        ...
