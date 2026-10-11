"""Redis click counters expire on their own when the flush never drains them."""

from uuid import uuid4

from app.modules.links.infrastructure.hit_counter import (
    PREFIX,
    TTL_SECONDS,
    RedisHitCounter,
)

from fakeredis.aioredis import FakeRedis


async def test_a_counter_gets_a_ttl_on_its_first_hit(redis: FakeRedis) -> None:
    """LNK: a key the flush never sees cannot live in Redis for ever."""
    counter = RedisHitCounter(redis)
    link_id = uuid4()

    await counter.hit(link_id)
    await counter.hit(link_id)

    assert int(await redis.get(f"{PREFIX}{link_id}")) == 2
    assert 0 < await redis.ttl(f"{PREFIX}{link_id}") <= TTL_SECONDS


async def test_restored_counters_keep_a_ttl(redis: FakeRedis) -> None:
    """Counts put back after a failed flush expire like fresh ones."""
    counter = RedisHitCounter(redis)
    link_id = uuid4()
    await counter.hit(link_id)
    drained = await counter.drain()
    assert drained == {link_id: 1}

    await counter.restore(drained)

    assert int(await redis.get(f"{PREFIX}{link_id}")) == 1
    assert await redis.ttl(f"{PREFIX}{link_id}") > 0
