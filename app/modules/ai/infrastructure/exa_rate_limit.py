"""The Exa allowance of our key, shared by every process: a rate and slots in flight.

Redis keeps the state: the hash `ai:exa:bucket` (a token bucket: `tokens`, `ts` and a
`cool` time set by a 429) and the sorted set `ai:exa:inflight` (one member per search
in flight, scored by when its lease ends, so a crashed process frees its slot). Each
change is one optimistic transaction (WATCH, then MULTI/EXEC): a process that races
another one retries, so no two searches take the same token or the last slot.

A search waits up to `queue_timeout_seconds` for a token and a slot; after that the
caller gets a busy answer. A 429 from Exa sets the cool-down, so every process waits
for the time Exa asked for.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast
from uuid import uuid4

from app.modules.ai.infrastructure.exa import ExaApi, ExaCallError
from app.settings import ExaSettings

import structlog
from redis.asyncio import Redis
from redis.exceptions import WatchError

log = structlog.get_logger(__name__)
T = TypeVar("T")

BUCKET_KEY = "ai:exa:bucket"
INFLIGHT_KEY = "ai:exa:inflight"
STATE_TTL_MS = 60_000
LEASE_MARGIN_SECONDS = 10.0  # a lease outlives Exa's own timeout by this much
DEFAULT_COOL_DOWN_SECONDS = 2.0  # a 429 without Retry-After
BUSY_RETRY_SECONDS = 1  # what a student is told when the local queue is full
MAX_POLL_SECONDS = 0.25  # re-check a slot or a cool-down at least this often


def _text(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


async def _wait(call: Awaitable[T] | T) -> T:
    """Await a redis-py call (its stubs type async results as `Awaitable | value`)."""
    return await cast("Awaitable[T]", call)


def _number(value: Any, default: float) -> float:
    try:
        return float(_text(value)) if value is not None else default
    except ValueError:
        return default


class ExaRateLimiter:
    """Waits for a token and a slot in Redis; `now` and `sleep` are injectable."""

    def __init__(
        self,
        redis: Redis,
        *,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Keep the Redis client and the clock."""
        self.redis = redis
        self._now = now
        self._sleep = sleep

    async def acquire(
        self,
        *,
        max_qps: int,
        max_concurrent: int,
        timeout_seconds: float,
        lease_seconds: float,
    ) -> str | None:
        """A lease id once a token and a slot are free, None past `timeout_seconds`.

        Release the lease when the search is over.
        """
        deadline = self._now() + timeout_seconds
        while True:
            outcome = await self._attempt(max_qps, max_concurrent, lease_seconds)
            if isinstance(outcome, str):
                return outcome
            if self._now() + outcome > deadline:
                return None
            await self._sleep(max(outcome, 0.001))

    async def release(self, lease: str) -> None:
        """Free the slot of a search that is over."""
        await self.redis.zrem(INFLIGHT_KEY, lease)

    async def cool_down(self, seconds: float) -> None:
        """Hold every search for `seconds`: Exa answered 429 and said so."""
        until = self._now() + seconds
        await _wait(self.redis.hset(BUCKET_KEY, "cool", str(until)))
        await self.redis.pexpire(BUCKET_KEY, STATE_TTL_MS + int(seconds * 1000))
        log.warning("web_search_cool_down", seconds=round(seconds, 1))

    async def _attempt(
        self, max_qps: int, max_concurrent: int, lease_seconds: float
    ) -> str | float:
        """One transaction: a lease id when granted, else the seconds to wait."""
        now = self._now()
        pipe = self.redis.pipeline(transaction=True)
        try:
            await pipe.watch(BUCKET_KEY, INFLIGHT_KEY)
            bucket = await _wait(pipe.hgetall(BUCKET_KEY))
            cool_until = _number(bucket.get("cool"), 0.0)
            if cool_until > now:
                return min(cool_until - now, MAX_POLL_SECONDS)
            active = int(await _wait(pipe.zcount(INFLIGHT_KEY, f"({now}", "+inf")))
            if active >= max_concurrent:
                return MAX_POLL_SECONDS
            tokens = min(
                float(max_qps),
                _number(bucket.get("tokens"), float(max_qps))
                + max(0.0, now - _number(bucket.get("ts"), now)) * max_qps,
            )
            if tokens < 1:
                return min((1 - tokens) / max_qps, MAX_POLL_SECONDS)
            lease = uuid4().hex
            pipe.multi()  # type: ignore[no-untyped-call]
            pipe.hset(BUCKET_KEY, mapping={"tokens": tokens - 1, "ts": now})
            pipe.pexpire(BUCKET_KEY, STATE_TTL_MS)
            pipe.zremrangebyscore(INFLIGHT_KEY, "-inf", now)
            pipe.zadd(INFLIGHT_KEY, {lease: now + lease_seconds})
            pipe.pexpire(INFLIGHT_KEY, int((lease_seconds + 60) * 1000))
            await pipe.execute()
            return lease
        except WatchError:
            return 0.0  # another process moved the state: look again at once
        finally:
            await pipe.reset()  # type: ignore[no-untyped-call]


class LimitedExa:
    """Implements `ExaApi`: every search waits for the shared allowance first.

    A full local queue is a busy answer (429 with a one-second retry); a 429 from Exa
    sets the cool-down for all processes, and the lease is always released.
    """

    def __init__(
        self, client: ExaApi, limiter: ExaRateLimiter, settings: ExaSettings
    ) -> None:
        """Store the wrapped client, the Redis limiter and the Exa settings."""
        self.client = client
        self.limiter = limiter
        self.settings = settings

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Run one search under the limit.

        Raises:
            ExaCallError: The queue was full (status 429), or Exa failed.
        """
        config = self.settings
        lease = await self.limiter.acquire(
            max_qps=config.max_qps,
            max_concurrent=config.max_concurrent,
            timeout_seconds=config.queue_timeout_seconds,
            lease_seconds=config.timeout_seconds + LEASE_MARGIN_SECONDS,
        )
        if lease is None:
            log.warning("web_search_queue_full", max_qps=config.max_qps)
            raise ExaCallError(
                status=429, retry_after=BUSY_RETRY_SECONDS, details="queue full"
            )
        try:
            return await self.client.search(body)
        except ExaCallError as error:
            if error.status == 429:
                seconds = error.retry_after
                await self.limiter.cool_down(
                    DEFAULT_COOL_DOWN_SECONDS if seconds is None else seconds
                )
            raise
        finally:
            await self.limiter.release(lease)
