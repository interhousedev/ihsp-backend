"""The shared Redis helpers: typed awaits, text decoding and the key lock."""

from app.shared.redis_util import RedisKeyLock, text, wait

import pytest
from fakeredis.aioredis import FakeRedis


class BusyError(Exception):
    """Raised when the lock is taken."""


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


def test_text_decodes_bytes_and_keeps_str() -> None:
    """Replies come as bytes or str depending on the client."""
    assert text(b"abc") == "abc"
    assert text("abc") == "abc"


async def test_wait_returns_the_awaited_value(redis: FakeRedis) -> None:
    """`wait` only narrows the redis-py type: the value is the reply."""
    await redis.set("k", "1")

    assert await wait(redis.incr("k")) == 2


async def test_the_second_holder_is_refused_until_release(redis: FakeRedis) -> None:
    """One holder at a time; the key is free again after the block."""
    lock = RedisKeyLock(redis)

    async with lock.hold("job", 60, BusyError):
        with pytest.raises(BusyError):
            async with lock.hold("job", 60, BusyError):
                pass
        assert await redis.ttl("job") > 0

    assert await redis.get("job") is None


async def test_release_leaves_a_lock_taken_by_someone_else(redis: FakeRedis) -> None:
    """After the TTL another process may hold the key; it is not deleted."""
    lock = RedisKeyLock(redis)
    token = await lock.acquire("job", 60)
    assert token is not None
    await redis.set("job", "other-token")

    await lock.release("job", token)

    assert await redis.get("job") == "other-token"


async def test_acquire_returns_none_when_held(redis: FakeRedis) -> None:
    """The non-raising form for jobs that just skip a run."""
    lock = RedisKeyLock(redis)

    assert await lock.acquire("job", 60) is not None
    assert await lock.acquire("job", 60) is None
