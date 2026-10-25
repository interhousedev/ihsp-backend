"""Redis cache of rendered room pages (``room:{slug}:{date}``)."""

from collections.abc import Collection

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = structlog.get_logger(__name__)


class RedisRoomPageCache:
    """Deletes the cached pages of rooms; an outage is logged, never raised."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def invalidate(self, slugs: Collection[str]) -> None:
        """Forget every cached day of the rooms."""
        try:
            for slug in slugs:
                keys = [key async for key in self.redis.scan_iter(f"room:{slug}:*")]
                if keys:
                    await self.redis.delete(*keys)
        except RedisError:
            logger.warning("room_cache_invalidate_failed", slugs=list(slugs))
