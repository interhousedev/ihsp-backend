"""Short-lived JSON tickets in Redis."""

import json
from typing import Any

from redis.asyncio import Redis


class RedisTicketStore:
    """Stores small JSON documents with a TTL."""

    def __init__(self, redis: Redis) -> None:
        """Keep the client."""
        self._redis = redis

    async def put(self, key: str, data: dict[str, Any], *, ttl: int) -> None:
        """Store or replace a document."""
        await self._redis.set(key, json.dumps(data), ex=ttl)

    async def get(self, key: str) -> dict[str, Any] | None:
        """Read a document."""
        raw = await self._redis.get(key)
        if raw is None:
            return None
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else None

    async def delete(self, key: str) -> None:
        """Remove a document."""
        await self._redis.delete(key)
