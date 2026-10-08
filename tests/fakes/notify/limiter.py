"""A SendLimiter that never waits and counts its calls."""


class CountingLimiter:
    """Implements SendLimiter for tests."""

    def __init__(self) -> None:
        """Start at zero."""
        self.acquired = 0

    async def acquire(self) -> None:
        """Count one message."""
        self.acquired += 1
