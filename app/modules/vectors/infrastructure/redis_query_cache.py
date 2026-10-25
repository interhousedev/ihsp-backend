"""Redis cache of question vectors."""

from collections.abc import Sequence

from app.modules.vectors.domain.packing import pack, unpack

from redis.asyncio import Redis


class RedisQueryCache:
    """Vectors as base64 half floats (2.7 KB each); the client decodes responses."""

    def __init__(self, redis: Redis) -> None:
        """Keep the Redis client."""
        self.redis = redis

    async def get(self, key: str) -> list[float] | None:
        """The cached vector, if any."""
        raw = await self.redis.get(key)
        return None if raw is None else unpack(raw)

    async def put(self, key: str, values: Sequence[float], ttl_seconds: int) -> None:
        """Remember a vector for `ttl_seconds`."""
        await self.redis.set(key, pack(values), ex=ttl_seconds)
