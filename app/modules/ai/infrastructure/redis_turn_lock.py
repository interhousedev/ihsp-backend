"""A Redis lock that allows one running turn per chat."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.modules.ai.domain.errors import TurnInProgressError
from app.shared.redis_util import RedisKeyLock

from redis.asyncio import Redis

LOCK_TTL_SECONDS = 15 * 60  # longer than the slowest turn (8 model calls)


class RedisTurnLock:
    """Implements TurnLock with the shared `SET NX EX` key lock on `ai:turn:{chat}`."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis
        self._lock = RedisKeyLock(redis)

    @asynccontextmanager
    async def hold(self, chat_id: UUID) -> AsyncIterator[None]:
        """Hold the chat's lock; raise TurnInProgressError if it is taken."""
        async with self._lock.hold(
            f"ai:turn:{chat_id}",
            LOCK_TTL_SECONDS,
            lambda: TurnInProgressError(params={"chat_id": str(chat_id)}),
        ):
            yield
