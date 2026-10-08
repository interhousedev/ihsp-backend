"""Revoked sessions/connectors (auth:revoked:{id})."""

from uuid import UUID

from redis.asyncio import Redis

# Longer than the access token lifetime (Hydra: 15 minutes) plus clock slack.
REVOCATION_TTL_SECONDS = 1000


class RedisRevocationList:
    """Ids that must be rejected until their access tokens have expired."""

    def __init__(self, redis: Redis) -> None:
        """Keep the client."""
        self._redis = redis

    async def revoke(self, identifier: UUID | str, *, ttl: int | None = None) -> None:
        """Put the id on the list."""
        await self._redis.set(
            f"auth:revoked:{identifier}", "1", ex=ttl or REVOCATION_TTL_SECONDS
        )

    async def is_revoked(self, identifier: UUID | str) -> bool:
        """True while the id is listed."""
        return bool(await self._redis.exists(f"auth:revoked:{identifier}"))
