"""Rate limit of 404 answers per IP on the public hosts (SL-10)."""

from app.shared.rate_limit import RateLimiter

NOT_FOUND_LIMIT = 60
NOT_FOUND_WINDOW_SECONDS = 600


class NotFoundCounter:
    """Counts 404 pages per IP; the 61st within 10 minutes raises RateLimitedError."""

    def __init__(self, rate_limiter: RateLimiter) -> None:
        """Store the shared rate limiter."""
        self.rate_limiter = rate_limiter

    async def count(self, ip: str | None) -> None:
        """Count one 404 for the IP."""
        await self.rate_limiter.hit(
            f"404:{ip or 'unknown'}",
            limit=NOT_FOUND_LIMIT,
            window_seconds=NOT_FOUND_WINDOW_SECONDS,
        )
