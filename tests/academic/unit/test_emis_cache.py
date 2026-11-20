"""The EMIS profile cache: Redis behind an in-process LFU, TTL on the clock (EMIS-C)."""

from dataclasses import replace
from typing import Any, cast
from uuid import UUID

from app.bootstrap.adapters.emis_profile_cache import CachedEmisSource
from app.shared.contracts.emis import EmisName, EmisProfile, EmisSource
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

from fakeredis.aioredis import FakeRedis

TTL = 3600


def _profile(user_id: UUID) -> EmisProfile:
    return EmisProfile(
        emis_student_id=int(user_id.int % 10_000),
        first_name="Ali",
        last_name="Karimov",
        middle_name=None,
        institution_id=10815,
        group_emis_id=3292,
        group_name="2TN2",
        current_semester=3,
        curriculum_id=555,
        institution_name=EmisName(uz="Lits", ru="Лицей", en="Lyceum"),
        direction="Tabiiy fanlar",
        speciality="Informatika",
    )


class CountingSource:
    """Stands in for the live EMIS source and counts the profile reads."""

    def __init__(self) -> None:
        self.calls: list[UUID] = []
        self.profile_for: dict[UUID, EmisProfile] = {}

    async def profile(self, user_id: UUID) -> EmisProfile:
        self.calls.append(user_id)
        return self.profile_for.get(user_id) or _profile(user_id)


def _cache(
    inner: CountingSource,
    redis: FakeRedis,
    clock: FixedClock,
    *,
    maxsize: int = 512,
    ttl: int = TTL,
) -> CachedEmisSource:
    return CachedEmisSource(
        cast(EmisSource, inner),
        redis=redis,  # type: ignore[arg-type]
        clock=clock,
        ttl_seconds=ttl,
        maxsize=maxsize,
    )


async def test_first_read_misses_then_memory_serves_the_next() -> None:
    inner = CountingSource()
    clock = FixedClock()
    cache = _cache(inner, FakeRedis(), clock)
    user = new_id()

    first = await cache.profile(user)
    second = await cache.profile(user)

    assert first == second == _profile(user)
    assert inner.calls == [user]
    assert (cache.hits, cache.misses) == (1, 1)


async def test_redis_serves_a_fresh_process_without_calling_emis() -> None:
    inner = CountingSource()
    clock = FixedClock()
    redis = FakeRedis()
    user = new_id()
    await _cache(inner, redis, clock).profile(user)

    other_process = _cache(inner, redis, clock)
    profile = await other_process.profile(user)

    assert profile == _profile(user)
    assert inner.calls == [user]
    assert other_process.hits == 1 and other_process.misses == 0


async def test_entry_expires_after_the_ttl_on_the_clock() -> None:
    inner = CountingSource()
    clock = FixedClock()
    cache = _cache(inner, FakeRedis(), clock, ttl=TTL)
    user = new_id()
    await cache.profile(user)

    clock.advance(seconds=TTL - 1)
    await cache.profile(user)
    assert len(inner.calls) == 1

    clock.advance(seconds=1)
    await cache.profile(user)
    assert len(inner.calls) == 2
    assert cache.misses == 2


async def test_expired_redis_entry_is_a_miss_even_when_redis_still_holds_it() -> None:
    inner = CountingSource()
    clock = FixedClock()
    redis = FakeRedis()
    user = new_id()
    await _cache(inner, redis, clock, ttl=TTL).profile(user)

    clock.advance(seconds=TTL + 1)
    await _cache(inner, redis, clock, ttl=TTL).profile(user)

    assert len(inner.calls) == 2


async def test_lfu_evicts_the_least_used_profile_from_memory() -> None:
    inner = CountingSource()
    clock = FixedClock()
    cache = _cache(inner, FakeRedis(), clock, maxsize=2)
    hot, cold, newcomer = new_id(), new_id(), new_id()

    await cache.profile(hot)
    await cache.profile(hot)
    await cache.profile(hot)
    await cache.profile(cold)
    await cache.profile(newcomer)

    assert cache.memory_size == 2
    assert cache.in_memory(hot)
    assert not cache.in_memory(cold)
    assert cache.in_memory(newcomer)


async def test_each_lookup_logs_the_cache_event(monkeypatch: Any) -> None:
    events: list[dict[str, Any]] = []

    class Log:
        def info(self, event: str, **fields: Any) -> None:
            events.append({"event": event, **fields})

    monkeypatch.setattr("app.bootstrap.adapters.emis_profile_cache.log", Log())
    inner = CountingSource()
    clock = FixedClock()
    cache = _cache(inner, FakeRedis(), clock)
    user = new_id()

    await cache.profile(user)
    clock.advance(seconds=10)
    await cache.profile(user)

    assert [e["event"] for e in events] == ["emis.cache", "emis.cache"]
    assert (events[0]["hit"], events[0]["source"]) == (False, "emis")
    assert (events[1]["hit"], events[1]["source"]) == (True, "memory")
    assert events[1]["age_s"] == 10
    assert events[1]["ttl_s"] == TTL


async def test_profile_round_trips_through_redis_unchanged() -> None:
    inner = CountingSource()
    clock = FixedClock()
    redis = FakeRedis()
    user = new_id()
    bare = replace(_profile(user), institution_name=None, direction=None)
    inner.profile_for[user] = bare
    await _cache(inner, redis, clock).profile(user)

    assert await _cache(inner, redis, clock).profile(user) == bare


async def test_other_reads_pass_through_to_the_source() -> None:
    class Inner(CountingSource):
        async def rating_book(self, user_id: UUID) -> str:
            return f"https://emis.example/{user_id}.pdf"

    inner = Inner()
    user = new_id()
    cache = _cache(inner, FakeRedis(), FixedClock())

    assert await cache.rating_book(user) == f"https://emis.example/{user}.pdf"
    assert inner.calls == []
