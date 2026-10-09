"""LIB-12: the admin status page: breaker, last calls, cache, hidden records."""

import datetime as dt
from collections.abc import Awaitable, Callable

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ItemStatus
from app.modules.library.infrastructure.redis_util import wait
from app.modules.library.ports.external_monitor import BreakerState
from app.modules.library.wiring_external import ExternalServices
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from tests.factories.library import make_external
from tests.fakes.clock import FixedClock

import pytest
from fakeredis.aioredis import FakeRedis

StoreItem = Callable[[Item], Awaitable[Item]]


async def test_a_quiet_connection_is_closed_with_nothing_to_show(
    external: ExternalServices, admin: Actor
) -> None:
    """LIB-12: no calls yet."""
    status = await external.get_status.execute(admin)

    assert status.breaker is BreakerState.CLOSED
    assert status.last_calls == []
    assert (status.cache.hits, status.cache.misses, status.cache.stale_served) == (
        0,
        0,
        0,
    )
    assert status.hidden_records == []


async def test_status_reads_the_breaker_calls_and_cache_counters(
    external: ExternalServices, admin: Actor, redis: FakeRedis, clock: FixedClock
) -> None:
    """LIB-12: what the connection did, from Redis."""
    open_until = str(clock.now().timestamp() + 30)
    await wait(
        redis.hset(
            "library:ext:breaker", mapping={"failures": "3", "open_until": open_until}
        )
    )
    await wait(
        redis.hset(
            "library:ext:cache_stats",
            mapping={"hits": "5", "misses": "2", "stale_served": "1"},
        )
    )
    await wait(
        redis.lpush(
            "library:ext:calls",
            '{"at": "2026-10-06T08:59:00+00:00", "ok": false, '
            '"ms": 8000, "path": "/api/x"}',
        )
    )

    status = await external.get_status.execute(admin)

    assert status.breaker is BreakerState.OPEN
    assert (status.cache.hits, status.cache.misses, status.cache.stale_served) == (
        5,
        2,
        1,
    )
    (call,) = status.last_calls
    assert (call.ok, call.ms, call.path) == (False, 8000, "/api/x")
    assert call.at == dt.datetime(2026, 10, 6, 8, 59, tzinfo=dt.UTC)


async def test_hidden_records_are_listed_as_cards(
    external: ExternalServices, admin: Actor, store_item: StoreItem
) -> None:
    """LIB-12: the librarians' hidden list (stored, unpublished)."""
    hidden = await store_item(
        make_external(
            title="Hidden one", external_id="1", status=ItemStatus.UNPUBLISHED
        )
    )
    await store_item(make_external(title="Visible", external_id="2"))

    status = await external.get_status.execute(admin)

    assert [(c.id, c.title) for c in status.hidden_records] == [
        (hidden.id, "Hidden one")
    ]


async def test_only_administration_sees_the_status(
    external: ExternalServices, student: Actor, librarian: Actor
) -> None:
    """LIB-12: students and librarians are refused."""
    for actor in (student, librarian):
        with pytest.raises(ForbiddenError):
            await external.get_status.execute(actor)


async def test_status_works_while_the_integration_is_off(
    external_off: ExternalServices, admin: Actor
) -> None:
    """LIB-12: Administration looks before switching on."""
    status = await external_off.get_status.execute(admin)

    assert status.breaker is BreakerState.CLOSED
