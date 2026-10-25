"""ID-1: pending registrations live 30 minutes in Redis under a hashed key."""

import asyncio
from uuid import UUID

from app.modules.identity.application.register_models import PendingReclaim
from app.modules.identity.infrastructure.emis.pending_store import RedisPendingStore
from app.shared.ids import hash_token

from fakeredis.aioredis import FakeRedis


def make_pending(email: str | None = None) -> PendingReclaim:
    return PendingReclaim(
        user_id=UUID(int=1),
        emis_login="student01",
        password_enc="vault:v1:abc",
        token_enc="vault:v1:def",
        email=email,
    )


def make_store(redis: FakeRedis) -> RedisPendingStore[PendingReclaim]:
    return RedisPendingStore(redis, prefix="reclaim", model=PendingReclaim)


async def test_a_value_round_trips_under_a_hashed_key(redis: FakeRedis) -> None:
    """ID-1: the bearer token is never a Redis key."""
    store = make_store(redis)

    token = await store.create(make_pending())

    assert await store.get(token) == make_pending()
    assert await redis.keys("*") == [f"reclaim:{hash_token(token)}"]
    assert 0 < await redis.ttl(f"reclaim:{hash_token(token)}") <= 1800


async def test_save_keeps_the_remaining_lifetime(redis: FakeRedis) -> None:
    """ID-1: updating a flow must not extend the 30 minutes."""
    store = make_store(redis)
    token = await store.create(make_pending())
    key = f"reclaim:{hash_token(token)}"
    await redis.expire(key, 100)

    await store.save(token, make_pending("a@example.com"))

    loaded = await store.get(token)
    assert loaded is not None
    assert loaded.email == "a@example.com"
    assert 0 < await redis.ttl(key) <= 100


async def test_unknown_expired_and_deleted_tokens_give_none(redis: FakeRedis) -> None:
    """ID-1: after 30 minutes the flow is gone."""
    store = make_store(redis)
    deleted = await store.create(make_pending())
    expiring = await store.create(make_pending())
    await redis.pexpire(f"reclaim:{hash_token(expiring)}", 1)
    await store.delete(deleted)
    await asyncio.sleep(0.05)

    assert await store.get(deleted) is None
    assert await store.get(expiring) is None
    assert await store.get("never-issued") is None


async def test_a_corrupt_value_is_treated_as_missing(redis: FakeRedis) -> None:
    """ID-1: a bad payload never crashes the flow, it just expires it."""
    store = make_store(redis)
    token = await store.create(make_pending())
    await redis.set(f"reclaim:{hash_token(token)}", "{not json")

    assert await store.get(token) is None
