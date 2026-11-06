"""30 second cache of the extra scopes of connectors (the OAuth overlay of A7)."""

import json
from collections.abc import Sequence
from uuid import UUID

from redis.asyncio import Redis

TTL_SECONDS = 30


def _key(connector_id: UUID) -> str:
    return f"mcp:overlay:{connector_id}"


class RedisScopeOverlayCache:
    """Scopes by connector; a grant clears the entries so it applies at once."""

    def __init__(self, redis: Redis) -> None:
        """Keep the client."""
        self._redis = redis

    async def get(self, connector_id: UUID) -> frozenset[str] | None:
        """The cached scopes, None when not cached."""
        raw = await self._redis.get(_key(connector_id))
        return None if raw is None else frozenset(json.loads(raw))

    async def put(self, connector_id: UUID, scopes: frozenset[str]) -> None:
        """Cache the scopes briefly."""
        await self._redis.set(
            _key(connector_id), json.dumps(sorted(scopes)), ex=TTL_SECONDS
        )

    async def invalidate(self, connector_ids: Sequence[UUID]) -> None:
        """Forget the cached extra scopes of these connectors."""
        if connector_ids:
            await self._redis.delete(*(_key(c) for c in connector_ids))
