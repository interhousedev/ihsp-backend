"""A Redis lock that allows one running question per notebook and student."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.modules.notebooks.domain.errors import BusyError
from app.shared.redis_util import RedisKeyLock

from redis.asyncio import Redis

LOCK_TTL_SECONDS = 5 * 60  # longer than the slowest answer (180 s timeout + retries)


class RedisTurnLock:
    """Implements TurnLock with the shared key lock on `nb:turn:{notebook}:{user}`."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis
        self._lock = RedisKeyLock(redis)

    @asynccontextmanager
    async def hold(self, notebook_id: UUID, user_id: UUID) -> AsyncIterator[None]:
        """Hold the lock; raise BusyError if it is taken (release is shielded)."""
        async with self._lock.hold(
            f"nb:turn:{notebook_id}:{user_id}",
            LOCK_TTL_SECONDS,
            lambda: BusyError(params={"what": "question"}),
        ):
            yield
