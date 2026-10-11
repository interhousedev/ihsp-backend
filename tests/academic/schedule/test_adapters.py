"""Redis adapters: import previews and the room page cache (spec -> Redis keys)."""

from app.modules.academic.infrastructure.schedule.import_store import RedisImportStore
from app.modules.academic.infrastructure.schedule.room_page_cache import (
    RedisRoomPageCache,
)
from app.shared.ids import new_id

from fakeredis.aioredis import FakeRedis


async def test_an_import_preview_round_trips_and_expires_after_an_hour(
    redis: FakeRedis,
) -> None:
    """UF-ADM-14: import:{id} lives for one hour."""
    store = RedisImportStore(redis)
    import_id = new_id()

    await store.save(import_id, {"rows": [{"kind": "new"}]})

    assert await store.load(import_id) == {"rows": [{"kind": "new"}]}
    assert 3500 < await redis.ttl(f"import:{import_id}") <= 3600
    await store.delete(import_id)
    assert await store.load(import_id) is None


async def test_a_missing_import_preview_is_none(redis: FakeRedis) -> None:
    """UF-ADM-14: unknown ids load as None."""
    assert await RedisImportStore(redis).load(new_id()) is None


async def test_room_pages_are_dropped_for_the_given_rooms_only(
    redis: FakeRedis,
) -> None:
    """ROOM-8: pages are refreshed when a lesson or PIN of the room changes."""
    await redis.set("room:102:2026-10-06", "<html>")
    await redis.set("room:102:2026-10-07", "<html>")
    await redis.set("room:103:2026-10-06", "<html>")

    await RedisRoomPageCache(redis).invalidate(["102"])

    assert await redis.keys("room:*") == ["room:103:2026-10-06"]


async def test_invalidating_without_rooms_does_nothing(redis: FakeRedis) -> None:
    """ROOM-8: an empty list is fine."""
    await redis.set("room:102:2026-10-06", "<html>")

    await RedisRoomPageCache(redis).invalidate([])

    assert await redis.dbsize() == 1
