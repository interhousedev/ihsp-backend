"""Redis storage of import previews (``import:{id}``, one hour)."""

import json
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

IMPORT_TTL_SECONDS = 3600


class RedisImportStore:
    """Keeps parsed previews between upload and confirmation."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    @staticmethod
    def _key(import_id: UUID) -> str:
        return f"import:{import_id}"

    async def save(self, import_id: UUID, payload: dict[str, Any]) -> None:
        """Store the preview for an hour."""
        await self.redis.set(
            self._key(import_id), json.dumps(payload), ex=IMPORT_TTL_SECONDS
        )

    async def load(self, import_id: UUID) -> dict[str, Any] | None:
        """Return the preview or None if it expired."""
        raw = await self.redis.get(self._key(import_id))
        if raw is None:
            return None
        loaded: dict[str, Any] = json.loads(raw)
        return loaded

    async def delete(self, import_id: UUID) -> None:
        """Forget the preview."""
        await self.redis.delete(self._key(import_id))
