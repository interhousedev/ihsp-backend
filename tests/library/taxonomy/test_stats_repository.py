"""LIB-16: daily counters, aggregates and the Redis side of the rollup."""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

from app.modules.library.domain.entities import Item, SubjectLink
from app.modules.library.domain.enums import ItemStatus, ReportReason
from app.modules.library.domain.taxonomy_stats import DayCounters
from app.modules.library.infrastructure.orm import ItemReport
from app.modules.library.infrastructure.redis_stats import RedisStatsRecorder
from app.modules.library.infrastructure.redis_stats_reader import (
    RedisStatsCounters,
    no_result_key,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.ids import new_id
from tests.factories.library import make_book, make_material
from tests.fakes.clock import FixedClock

from fakeredis.aioredis import FakeRedis

StoreItem = Callable[[Item], Awaitable[Item]]
DAY = date(2026, 10, 5)
NEXT_DAY = date(2026, 10, 6)


async def test_upsert_sets_the_counters_and_repeating_changes_nothing(
    uow_factory: UowFactory,
) -> None:
    """LIB-16: the rollup is idempotent; a later value replaces the earlier one."""
    item_id = new_id()
    async with uow_factory() as uow:
        await uow.stats.upsert_day(item_id, DAY, 3, 2, 1)
        await uow.stats.upsert_day(item_id, DAY, 3, 2, 1)
        same = await uow.stats.totals(DAY, DAY)
        await uow.stats.upsert_day(item_id, DAY, 5, 3, 1)
        changed = await uow.stats.totals(DAY, DAY)

    assert same == (3, 2)
    assert changed == (5, 3)


async def test_totals_and_top_items_cover_only_the_window(
    uow_factory: UowFactory,
) -> None:
    """LIB-16: opens and readers add up per window; top items are ranked by opens."""
    popular, quiet, unseen = new_id(), new_id(), new_id()
    async with uow_factory() as uow:
        await uow.stats.upsert_day(popular, DAY, 10, 4, 0)
        await uow.stats.upsert_day(popular, NEXT_DAY, 5, 2, 1)
        await uow.stats.upsert_day(quiet, DAY, 4, 4, 0)
        await uow.stats.upsert_day(unseen, DAY - timedelta(days=30), 99, 9, 0)
        await uow.stats.upsert_day(new_id(), DAY, 0, 0, 2)
        totals = await uow.stats.totals(DAY, NEXT_DAY)
        top = await uow.stats.top_items(DAY, NEXT_DAY, limit=5)
        short = await uow.stats.top_items(DAY, NEXT_DAY, limit=1)
        nothing = await uow.stats.totals(date(2020, 1, 1), date(2020, 1, 2))

    assert totals == (19, 10)
    assert top == [(popular, 15), (quiet, 4)]
    assert short == [(popular, 15)]
    assert nothing == (0, 0)


async def test_items_are_counted_by_status(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-16: items_by_status lists the statuses that have items."""
    for status in (ItemStatus.PUBLISHED, ItemStatus.PUBLISHED, ItemStatus.HELD):
        await store_item(make_book(status=status))
    async with uow_factory() as uow:
        counts = await uow.stats.item_status_counts()

    assert counts[ItemStatus.PUBLISHED] >= 2
    assert counts[ItemStatus.HELD] >= 1


async def test_reports_are_counted_by_reason_in_the_window(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-16: reports_by_reason counts reports filed in the window."""
    book = await store_item(make_book())
    since = datetime(2030, 1, 1, tzinfo=UTC)
    until = since + timedelta(days=1)
    async with uow_factory() as uow:
        for reason, filed in (
            (ReportReason.SPAM, since + timedelta(hours=1)),
            (ReportReason.SPAM, since + timedelta(hours=2)),
            (ReportReason.COPYRIGHT, since + timedelta(hours=3)),
            (ReportReason.OTHER, until + timedelta(hours=1)),
        ):
            uow.session.add(
                ItemReport(
                    item_id=book.id,
                    reporter_id=new_id(),
                    reason=reason.value,
                    created_at=filed,
                )
            )
        await uow.session.flush()
        counts = await uow.stats.report_counts(since, until)

    assert counts == {ReportReason.SPAM: 2, ReportReason.COPYRIGHT: 1}


async def test_uploads_are_counted_per_utc_day(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-16: uploads_by_day counts materials only, by the day they were created."""
    since = datetime(2031, 3, 1, tzinfo=UTC)
    until = since + timedelta(days=3)
    for hours in (1, 5, 30):
        await store_item(make_material(now=since + timedelta(hours=hours)))
    await store_item(make_book(now=since + timedelta(hours=2)))
    async with uow_factory() as uow:
        counts = await uow.stats.uploads_by_day(since, until)

    assert counts == {date(2031, 3, 1): 2, date(2031, 3, 2): 1}


async def test_subjects_with_published_materials(
    uow_factory: UowFactory, store_item: StoreItem
) -> None:
    """LIB-16: subjects_without_materials is the complement of this set."""
    covered, drafted = new_id(), new_id()
    published = await store_item(make_material())
    draft = await store_item(make_material(status=ItemStatus.DRAFT))
    async with uow_factory() as uow:
        await uow.items.set_subject_links(published.id, [SubjectLink(covered)])
        await uow.items.set_subject_links(draft.id, [SubjectLink(drafted)])
        subjects = await uow.stats.subject_ids_with_materials()

    assert covered in subjects
    assert drafted not in subjects


# - - - Redis - - -


async def test_counters_written_by_the_recorder_are_read_back(
    redis: FakeRedis, clock: FixedClock
) -> None:
    """LIB-16: opens, distinct readers and offline saves per item and day."""
    recorder = RedisStatsRecorder(redis, clock)
    counters = RedisStatsCounters(redis)
    item, other, reader = new_id(), new_id(), new_id()
    await recorder.opened(item, reader)
    await recorder.opened(item, reader)
    await recorder.opened(item, new_id())
    await recorder.opened(other, None)
    await recorder.offline_saved(other)

    day = await counters.day(clock.now().date())

    assert day[item] == DayCounters(opens=3, readers=2, offline_saves=0)
    assert day[other] == DayCounters(opens=1, readers=0, offline_saves=1)
    assert await counters.day(date(2000, 1, 1)) == {}


async def test_discarding_a_day_removes_hash_and_reader_sets(
    redis: FakeRedis, clock: FixedClock
) -> None:
    """LIB-16: processed keys are deleted."""
    recorder = RedisStatsRecorder(redis, clock)
    counters = RedisStatsCounters(redis)
    item = new_id()
    await recorder.opened(item, new_id())
    day = clock.now().date()

    await counters.discard(day, [item])

    assert await counters.day(day) == {}
    assert await redis.keys("library:stats:*") == []


async def test_junk_in_the_hash_is_ignored(redis: FakeRedis, clock: FixedClock) -> None:
    """LIB-16: a foreign field does not break the rollup."""
    counters = RedisStatsCounters(redis)
    day = clock.now().date()
    await redis.hset(f"library:stats:{day.isoformat()}", "garbage", "5")
    await redis.hset(f"library:stats:{day.isoformat()}", f"{new_id()}:opens", "x")

    result = await counters.day(day)

    assert [c.opens for c in result.values()] == [0]


async def test_searches_without_results_are_ranked(redis: FakeRedis) -> None:
    """LIB-16: top queries of a day, most frequent first."""
    counters = RedisStatsCounters(redis)
    await redis.hset(no_result_key("2026-10-05"), mapping={"b": "2", "a": "2", "c": "9"})

    top = await counters.no_results(DAY, limit=2)

    assert list(top.items()) == [("c", 9), ("a", 2)]
    assert await counters.no_results(NEXT_DAY, limit=2) == {}
