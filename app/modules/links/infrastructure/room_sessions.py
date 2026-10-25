"""Redis room sessions (`room-session:{slug}:{token}` -> PIN, twelve hours)."""

import secrets

from app.modules.links.ports.room_sessions import SESSION_SECONDS

from redis.asyncio import Redis

MAX_TOKEN_LENGTH = 64


def _key(slug: str, token: str) -> str:
    return f"room-session:{slug}:{token}"


class RedisRoomSessions:
    """Stores the PIN a session was opened with, so a changed PIN ends it."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def open(self, slug: str, pin: str) -> str:
        """Start a session and return its random token."""
        token = secrets.token_urlsafe(24)
        await self.redis.set(_key(slug, token), pin, ex=SESSION_SECONDS)
        return token

    async def pin_of(self, slug: str, token: str) -> str | None:
        """Return the PIN of a known session, else None."""
        if not token or len(token) > MAX_TOKEN_LENGTH or not token.isascii():
            return None
        value = await self.redis.get(_key(slug, token))
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)
