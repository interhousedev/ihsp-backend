"""A7: the extra scopes of connectors, cached for 30 seconds."""

from datetime import UTC, datetime
from uuid import uuid4

from app.bootstrap.adapters.mcp_offers import ScopeOverlayAdapter
from app.modules.identity.infrastructure.redis.scope_overlay_cache import (
    TTL_SECONDS,
    RedisScopeOverlayCache,
)
from tests.identity.support import World

from fakeredis.aioredis import FakeRedis


async def test_cache_round_trip_expiry_and_invalidation(redis: FakeRedis) -> None:
    """A7: unknown is None, an empty set is cached, a grant clears the entry."""
    cache = RedisScopeOverlayCache(redis)
    first, second = uuid4(), uuid4()

    assert await cache.get(first) is None
    await cache.put(first, frozenset({"marks:read", "files:read"}))
    await cache.put(second, frozenset())

    assert await cache.get(first) == {"marks:read", "files:read"}
    assert await cache.get(second) == frozenset()
    assert 0 < await redis.ttl(f"mcp:overlay:{first}") <= TTL_SECONDS
    await cache.invalidate([first])
    await cache.invalidate([])
    assert await cache.get(first) is None
    assert await cache.get(second) == frozenset()


async def test_adapter_reads_the_grant_then_serves_it_from_the_cache(
    auth_world: World, redis: FakeRedis
) -> None:
    """A7: a read fills the cache, so later changes wait for the invalidation."""
    user = await auth_world.add_user()
    connector = auth_world.add_connector(user, extra_scopes=["marks:read"])
    cache = RedisScopeOverlayCache(redis)
    adapter = ScopeOverlayAdapter(auth_world.uow, cache)

    assert await adapter.extra_scopes(connector.id) == {"marks:read"}
    del auth_world.store.connectors[connector.id]
    assert await adapter.extra_scopes(connector.id) == {"marks:read"}
    await cache.invalidate([connector.id])
    assert await adapter.extra_scopes(connector.id) == frozenset()


async def test_a_revoked_connector_has_no_extra_scopes(
    auth_world: World, redis: FakeRedis
) -> None:
    """A7: revocation beats any grant."""
    user = await auth_world.add_user()
    connector = auth_world.add_connector(
        user,
        extra_scopes=["marks:read"],
        revoked_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    adapter = ScopeOverlayAdapter(auth_world.uow, RedisScopeOverlayCache(redis))

    assert await adapter.extra_scopes(connector.id) == frozenset()
    assert await adapter.extra_scopes(uuid4()) == frozenset()
