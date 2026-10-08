"""AI-8: Redis counters, summaries and the per-chat lock (fakeredis)."""

from datetime import UTC, date, datetime, timedelta

from app.modules.ai.domain.errors import TurnInProgressError
from app.modules.ai.infrastructure.redis_budget_store import RedisBudgetStore
from app.modules.ai.infrastructure.redis_summary_store import RedisSummaryStore
from app.modules.ai.infrastructure.redis_turn_lock import RedisTurnLock
from app.modules.ai.ports.summary_store import StoredSummary
from app.shared.ids import new_id

import pytest
from fakeredis.aioredis import FakeRedis

# Redis expires keys by the wall clock, so the window must end in the future.
END = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=5)


async def test_session_window_holds_tokens_and_expires_with_the_window(
    redis: FakeRedis,
) -> None:
    """Redis keys: ai:session:{user} has used + ends_at and expires at the end."""
    store = RedisBudgetStore(redis)
    user = new_id()
    assert await store.session(user) is None

    await store.open_session(user, END)
    await store.add_session(user, 150)
    await store.add_session(user, 50)

    window = await store.session(user)
    assert window is not None and (window.used, window.ends_at) == (200, END)
    assert await redis.ttl(f"ai:session:{user}") > 0
    assert await redis.expiretime(f"ai:session:{user}") == int(END.timestamp())


async def test_reopening_a_window_resets_the_counter(redis: FakeRedis) -> None:
    """A new window starts from zero."""
    store = RedisBudgetStore(redis)
    user = new_id()
    await store.open_session(user, END)
    await store.add_session(user, 99)

    await store.open_session(user, END + timedelta(hours=5))

    window = await store.session(user)
    assert window is not None and window.used == 0


async def test_day_counter_is_kept_for_48_hours(redis: FakeRedis) -> None:
    """Redis keys: ai:day:{user}:{date}, TTL 48 h."""
    store = RedisBudgetStore(redis)
    user, day = new_id(), date(2026, 10, 6)

    await store.add_day(user, day, 300)
    await store.add_day(user, day, 20)

    assert await store.day_used(user, day) == 320
    assert await store.day_used(user, date(2026, 10, 7)) == 0
    assert 47 * 3600 < await redis.ttl(f"ai:day:{user}:2026-10-06") <= 48 * 3600


async def test_summary_round_trip_with_a_30_day_ttl(redis: FakeRedis) -> None:
    """Redis keys: ai:summary:{chat_id}, TTL 30 days."""
    store = RedisSummaryStore(redis)
    chat = new_id()
    assert await store.get(chat) is None

    await store.put(chat, StoredSummary(text="short", upto_seq=12))

    assert await store.get(chat) == StoredSummary(text="short", upto_seq=12)
    assert 29 * 86400 < await redis.ttl(f"ai:summary:{chat}") <= 30 * 86400


async def test_turn_lock_is_exclusive_and_released(redis: FakeRedis) -> None:
    """One turn per chat; the lock is freed on exit, also after an error."""
    lock = RedisTurnLock(redis)
    chat = new_id()

    async with lock.hold(chat):
        with pytest.raises(TurnInProgressError):
            async with lock.hold(chat):
                pass
    async with lock.hold(chat):
        pass

    with pytest.raises(RuntimeError):
        async with lock.hold(chat):
            raise RuntimeError("boom")
    async with lock.hold(chat):
        pass
