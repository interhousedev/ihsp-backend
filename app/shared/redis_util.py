"""Shared redis-py helpers: typed awaits, text decoding and a `SET NX EX` key lock."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TypeVar, cast

from app.shared.ids import random_token

from redis.asyncio import Redis

T = TypeVar("T")


async def wait(call: Awaitable[T] | T) -> T:
    """Await a redis-py call (its stubs type async results as `Awaitable | value`)."""
    return await cast("Awaitable[T]", call)


def text(value: bytes | str) -> str:
    """Decode a Redis reply that may be bytes or str (`decode_responses` or not)."""
    return value.decode() if isinstance(value, bytes) else value


class RedisKeyLock:
    """A lock on one key: `SET NX EX`, released only by the holder's token.

    `acquire` returns the token or None when the key is held; `hold` is the context
    manager form and raises what `busy` returns when the key is held. The release
    is shielded: a cancelled holder must not leave the key for its whole TTL.
    """

    def __init__(self, redis: Redis) -> None:
        """Store the Redis client."""
        self.redis = redis

    async def acquire(self, key: str, ttl_seconds: int) -> str | None:
        """Take the key for `ttl_seconds`; None when someone else holds it."""
        token = random_token(12)
        if not await self.redis.set(key, token, nx=True, ex=ttl_seconds):
            return None
        return token

    async def release(self, key: str, token: str) -> None:
        """Free the key if `token` still holds it (an expired lock is left alone)."""
        current = await self.redis.get(key)
        if current is not None and text(current) == token:
            await self.redis.delete(key)

    @asynccontextmanager
    async def hold(
        self, key: str, ttl_seconds: int, busy: Callable[[], Exception]
    ) -> AsyncIterator[None]:
        """Hold the key for the block; raise `busy()` when it is already held."""
        token = await self.acquire(key, ttl_seconds)
        if token is None:
            raise busy()
        try:
            yield
        finally:
            await asyncio.shield(self.release(key, token))
