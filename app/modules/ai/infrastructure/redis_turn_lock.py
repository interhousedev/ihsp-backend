"""A Redis lock that allows one running turn per chat."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.modules.ai.domain.errors import TurnInProgressError
from app.shared.ids import random_token

from redis.asyncio import Redis

LOCK_TTL_SECONDS = 15 * 60  # longer than the slowest turn (8 model calls)


class RedisTurnLock:
    """Implements TurnLock with `SET NX EX`."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    @asynccontextmanager
    async def hold(self, chat_id: UUID) -> AsyncIterator[None]:
        """Hold the chat's lock; raise TurnInProgressError if it is taken."""
        key = f"ai:turn:{chat_id}"
        token = random_token(12)
        if not await self.redis.set(key, token, nx=True, ex=LOCK_TTL_SECONDS):
            raise TurnInProgressError(params={"chat_id": str(chat_id)})
        try:
            yield
        finally:
            current = await self.redis.get(key)
            if current is not None and _text(current) == token:
                await self.redis.delete(key)


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value
