"""Rate limit of link creation per user (SL-10)."""

from uuid import UUID

from app.shared.rate_limit import RateLimiter

LINKS_PER_HOUR = 60
WINDOW_SECONDS = 3600


class LinkCreationLimit:
    """Allows 60 new links, shares or resources per user and hour."""

    def __init__(self, rate_limiter: RateLimiter) -> None:
        """Store the shared rate limiter."""
        self.rate_limiter = rate_limiter

    async def hit(self, user_id: UUID) -> None:
        """Count one creation; raise RateLimitedError when over the limit."""
        await self.rate_limiter.hit(
            f"links:{user_id}", limit=LINKS_PER_HOUR, window_seconds=WINDOW_SECONDS
        )
