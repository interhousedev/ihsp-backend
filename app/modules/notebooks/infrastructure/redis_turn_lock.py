"""A Redis lock that allows one running question per notebook and student."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.modules.notebooks.domain.errors import BusyError
from app.shared.ids import random_token

from redis.asyncio import Redis

LOCK_TTL_SECONDS = 5 * 60  # longer than the slowest answer (180 s timeout + retries)


class RedisTurnLock:
    """Implements TurnLock with `SET NX EX` on `nb:turn:{notebook}:{user}`."""

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    @asynccontextmanager
    async def hold(self, notebook_id: UUID, user_id: UUID) -> AsyncIterator[None]:
        """Hold the lock; raise BusyError if it is taken."""
        key = f"nb:turn:{notebook_id}:{user_id}"
        token = random_token(12)
        if not await self.redis.set(key, token, nx=True, ex=LOCK_TTL_SECONDS):
            raise BusyError(params={"what": "question"})
        try:
            yield
        finally:
            # Shielded: a client that hangs up cancels this task again and again,
            # and a half-done release would block the next question for minutes.
            await asyncio.shield(self._release(key, token))

    async def _release(self, key: str, token: str) -> None:
        current = await self.redis.get(key)
        if current is not None and _text(current) == token:
            await self.redis.delete(key)


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value
