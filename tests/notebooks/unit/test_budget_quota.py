"""NB-14 (§ 3.6, § 6.3 "Budget"): weighted tokens, the budget window, daily quotas."""

import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.modules.notebooks.application.budget import NotebookBudget
from app.modules.notebooks.application.get_usage import GetUsage
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import (
    BusyError,
    LimitReachedError,
    QuotaExceededError,
)
from app.modules.notebooks.domain.tokens import Usage, estimate_cost, estimate_tokens
from app.modules.notebooks.infrastructure.redis_budget_store import RedisBudgetStore
from app.modules.notebooks.infrastructure.redis_quota_store import RedisQuotaStore
from app.settings import Settings
from app.shared.clock import TASHKENT, local_today
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

# 2026-10-06 22:00 UTC is 03:00 on the 7th in Tashkent (UTC+5).
LATE = datetime(2026, 10, 6, 18, 59, tzinfo=UTC)  # 23:59 Tashkent, the 6th


def _limits(settings: Settings, **limits: int) -> Settings:
    return settings.model_copy(
        update={"limits": settings.limits.model_copy(update=limits)}
    )


def _near_now() -> datetime:
    """A moment close to the real time.

    Redis drops a key whose `EXPIREAT` lies in the past, and the budget session
    window expires at `now + 5 h` on the application clock, so the session tests
    cannot run at the default fixed moment of 2026-10-06 once the real date has
    passed it. Everything else is relative to this moment.
    """
    return datetime.now(UTC).replace(microsecond=0)


def _early_in_the_day() -> datetime:
    """The next 01:00 in Tashkent: close to now, and 5 hours later is the same day."""
    now = datetime.now(TASHKENT)
    start = now.replace(hour=1, minute=0, second=0, microsecond=0)
    if start <= now:
        start += timedelta(days=1)
    return start.astimezone(UTC)


@pytest_asyncio.fixture
async def budget(
    redis: FakeRedis, clock: FixedClock, settings: Settings
) -> NotebookBudget:
    """The budget over fakeredis with the default limits."""
    return NotebookBudget(RedisBudgetStore(redis), clock, settings)


@pytest_asyncio.fixture
async def quota(
    redis: FakeRedis, clock: FixedClock, settings: Settings
) -> QuotaService:
    """The quota service over fakeredis with the default limits."""
    return QuotaService(RedisQuotaStore(redis), clock, settings)


@pytest.fixture
def user() -> UUID:
    """A student id."""
    return new_id()


# - - - weighted tokens - - -


def test_uncached_call_weighs_input_plus_five_times_output() -> None:
    """NB-14: a 40k-token question with a 800-token answer is about 44k."""
    assert Usage(input=40_000, output=800).weighted == 44_000


def test_cached_input_costs_a_tenth() -> None:
    """NB-14: `cached` is a subset of `input` and is billed at 10 percent."""
    usage = Usage(input=40_000, cached=39_000, output=800)

    assert usage.weighted == 1_000 + 3_900 + 4_000


def test_fractions_round_up() -> None:
    """NB-14: the weighted value is a whole number, rounded up."""
    assert Usage(input=10, cached=5).weighted == 5 + 1
    assert Usage(input=1, cached=1).weighted == 1
    assert Usage().weighted == 0


@pytest.mark.parametrize("cached", [0, 1, 3, 7, 10, 30, 70, 99, 12_345, 1_000_001])
def test_weighted_matches_integer_arithmetic(cached: int) -> None:
    """NB-14: floating point never adds a token (uncached + ceil(cached/10) + 5 out)."""
    usage = Usage(input=cached + 12_345, cached=cached, output=17)

    assert usage.weighted == 12_345 + math.ceil(cached / 10) + 85


def test_usages_add_up_for_a_repair_call() -> None:
    """NB-14: a second call adds to the first one."""
    total = Usage(100, 10, 40, 5) + Usage(200, 20, 0, None)

    assert total == Usage(300, 30, 40, 5)
    assert total.weighted == 260 + 4 + 150


def test_estimate_before_a_call_is_chars_over_2_8_plus_five_times_max_tokens() -> None:
    """NB-14: `ceil(chars / 2.8) + max_tokens x 5`."""
    assert estimate_tokens(2800) == 1000
    assert estimate_tokens(2801) == 1001
    assert estimate_tokens(0) == 0
    assert estimate_cost(2800, 1000) == 1000 + 5000


# - - - the budget (session window and Tashkent day) - - -


async def test_a_new_student_has_the_full_budget(
    budget: NotebookBudget, user: UUID, clock: FixedClock
) -> None:
    """NB-14: nothing used, no open session, the day resets at Tashkent midnight."""
    info = await budget.usage(user)

    assert (info.session.used, info.session.limit) == (0, 1_500_000)
    assert info.session.resets_at is None
    assert (info.day.used, info.day.limit) == (0, 4_000_000)
    assert info.day.resets_at == datetime(2026, 10, 6, 19, 0, tzinfo=UTC)


async def test_used_tokens_count_in_the_session_and_the_day(
    redis: FakeRedis, settings: Settings, user: UUID
) -> None:
    """NB-14: one call adds to both counters; the session ends 5 hours later."""
    clock = FixedClock(_near_now())
    budget = NotebookBudget(RedisBudgetStore(redis), clock, settings)

    await budget.add(user, Usage(input=1000, cached=500, output=100).weighted)
    await budget.add(user, 200)

    info = await budget.usage(user)
    assert info.session.used == info.day.used == 500 + 50 + 500 + 200
    assert info.session.resets_at == clock.now() + timedelta(hours=5)


async def test_zero_and_negative_amounts_are_ignored(
    budget: NotebookBudget, user: UUID
) -> None:
    """NB-14: a failed call that used nothing opens no session."""
    await budget.add(user, 0)
    await budget.add(user, -50)

    info = await budget.usage(user)
    assert info.session.used == info.day.used == 0
    assert info.session.resets_at is None


async def test_users_have_separate_budgets(budget: NotebookBudget, user: UUID) -> None:
    """NB-14: counters are per student."""
    await budget.add(user, 1000)

    other = await budget.usage(new_id())

    assert other.day.used == 0


async def test_request_over_the_session_limit_is_refused_before_the_call(
    redis: FakeRedis, settings: Settings, user: UUID
) -> None:
    """NB-14: `require` raises `LimitReachedError` with the scope and reset time."""
    clock = FixedClock(_near_now())
    budget = NotebookBudget(RedisBudgetStore(redis), clock, settings)
    await budget.add(user, 1_499_000)

    with pytest.raises(LimitReachedError) as caught:
        await budget.require(user, 2_000)

    assert caught.value.status == 429
    assert caught.value.params["scope"] == "session"
    resets_at = clock.now() + timedelta(hours=5)
    assert caught.value.params["resets_at"] == resets_at.isoformat()
    await budget.require(user, 1_000)  # exactly the limit is still fine


async def test_request_over_the_day_limit_is_refused_until_midnight(
    redis: FakeRedis, settings: Settings, user: UUID
) -> None:
    """NB-14: the day scope resets at 00:00 in Tashkent."""
    clock = FixedClock(_near_now())
    small_day = _limits(settings, nb_daily_tokens_student=10_000)
    budget = NotebookBudget(RedisBudgetStore(redis), clock, small_day)
    await budget.add(user, 9_500)

    with pytest.raises(LimitReachedError) as caught:
        await budget.require(user, 600)

    midnight = datetime.combine(
        local_today(clock) + timedelta(days=1), datetime.min.time(), tzinfo=TASHKENT
    ).astimezone(UTC)
    assert caught.value.params == {
        "scope": "day",
        "resets_at": midnight.isoformat(),
    }


async def test_when_both_limits_are_hit_the_later_reset_is_reported(
    redis: FakeRedis, settings: Settings, user: UUID
) -> None:
    """NB-14: the student learns when they can really continue."""
    clock = FixedClock(_near_now())
    tight = _limits(
        settings, nb_session_tokens_student=1_000, nb_daily_tokens_student=1_000
    )
    budget = NotebookBudget(RedisBudgetStore(redis), clock, tight)
    await budget.add(user, 900)

    hit = await budget.check(user, 500)

    assert hit is not None
    info = await budget.usage(user)
    assert info.session.resets_at is not None and info.day.resets_at is not None
    assert hit.resets_at == max(info.session.resets_at, info.day.resets_at)


async def test_no_limit_is_hit_when_there_is_room(
    budget: NotebookBudget, user: UUID
) -> None:
    """NB-14: `check` answers None when the call fits."""
    await budget.add(user, 100)

    assert await budget.check(user, 1_000_000) is None


async def test_a_new_session_window_opens_after_five_hours_the_day_goes_on(
    redis: FakeRedis, settings: Settings, user: UUID
) -> None:
    """NB-14: the session counter starts again, the day counter does not."""
    clock = FixedClock(_early_in_the_day())  # the new window stays within the day
    budget = NotebookBudget(RedisBudgetStore(redis), clock, settings)
    await budget.add(user, 700)
    first_end = clock.now() + timedelta(hours=5)

    clock.set(first_end + timedelta(seconds=1))
    expired = await budget.usage(user)
    await budget.add(user, 300)
    renewed = await budget.usage(user)

    assert expired.session.used == 0 and expired.session.resets_at is None
    assert renewed.session.used == 300
    assert renewed.session.resets_at == clock.now() + timedelta(hours=5)
    assert local_today(clock) == local_today(FixedClock(first_end))
    assert renewed.day.used == 1000


async def test_the_day_counter_starts_again_at_midnight_in_tashkent(
    redis: FakeRedis, settings: Settings, user: UUID
) -> None:
    """NB-14: 23:59 in Tashkent is still the old day, 00:01 is a new one."""
    clock = FixedClock(LATE)
    budget = NotebookBudget(RedisBudgetStore(redis), clock, settings)
    await budget.add(user, 5_000)
    before = await budget.usage(user)

    clock.advance(minutes=2)
    after = await budget.usage(user)

    assert before.day.used == 5_000
    assert before.day.resets_at == datetime(2026, 10, 6, 19, 0, tzinfo=UTC)
    assert after.day.used == 0
    assert after.day.resets_at == datetime(2026, 10, 7, 19, 0, tzinfo=UTC)


# - - - daily quotas and the concurrency limit - - -


async def test_reserve_counts_the_total_and_the_own_counter(
    quota: QuotaService, user: UUID
) -> None:
    """NB-14: slides count in `artifacts` and in `slides`; reports only in the total."""
    await quota.reserve(user, ArtifactKind.REPORT, new_id())
    await quota.reserve(user, ArtifactKind.SLIDES, new_id())

    snapshot = await quota.snapshot(user)

    assert snapshot["artifacts"].used == 2
    assert snapshot["slides"].used == 1
    assert snapshot["infographic"].used == 0
    assert snapshot["audio_overview"].used == 0
    assert {name: part.limit for name, part in snapshot.items()} == {
        "artifacts": 20,
        "audio_overview": 0,
        "slides": 6,
        "infographic": 6,
    }


async def test_21st_output_of_the_day_is_refused_with_kind_limit_and_reset(
    quota: QuotaService, user: UUID
) -> None:
    """NB-14: `QuotaExceededError` carries kind, limit and `resets_at`."""
    for _ in range(20):
        artifact_id = new_id()
        await quota.reserve(user, ArtifactKind.QUIZ, artifact_id)
        await quota.finished(user, artifact_id)

    with pytest.raises(QuotaExceededError) as caught:
        await quota.reserve(user, ArtifactKind.QUIZ, new_id())

    assert caught.value.status == 429
    assert caught.value.params == {
        "kind": "artifacts",
        "limit": 20,
        "resets_at": datetime(2026, 10, 6, 19, 0, tzinfo=UTC).isoformat(),
    }
    assert (await quota.snapshot(user))["artifacts"].used == 20


async def test_slides_have_their_own_daily_limit_of_six(
    quota: QuotaService, user: UUID
) -> None:
    """NB-14: the 7th slide deck is refused although the total has room."""
    for _ in range(6):
        artifact_id = new_id()
        await quota.reserve(user, ArtifactKind.SLIDES, artifact_id)
        await quota.finished(user, artifact_id)

    with pytest.raises(QuotaExceededError) as caught:
        await quota.reserve(user, ArtifactKind.SLIDES, new_id())

    assert caught.value.params["kind"] == "slides"
    assert caught.value.params["limit"] == 6
    await quota.reserve(user, ArtifactKind.REPORT, new_id())


async def test_refused_request_leaves_nothing_counted_or_running(
    quota: QuotaService, user: UUID
) -> None:
    """NB-14: a refusal does not use up the quota or a running slot."""
    for _ in range(6):
        artifact_id = new_id()
        await quota.reserve(user, ArtifactKind.INFOGRAPHIC, artifact_id)
        await quota.finished(user, artifact_id)

    with pytest.raises(QuotaExceededError):
        await quota.reserve(user, ArtifactKind.INFOGRAPHIC, new_id())

    snapshot = await quota.snapshot(user)
    assert (snapshot["artifacts"].used, snapshot["infographic"].used) == (6, 6)
    assert await quota.running_count(user) == 0


async def test_audio_overview_counter_is_switched_off(
    quota: QuotaService, user: UUID
) -> None:
    """The user decided against audio and video: its counter has a limit of 0."""
    snapshot = await quota.snapshot(user)

    assert (snapshot["audio_overview"].used, snapshot["audio_overview"].limit) == (0, 0)
    with pytest.raises(QuotaExceededError) as caught:
        await quota.reserve(user, ArtifactKind.AUDIO_OVERVIEW, new_id())
    assert caught.value.params["kind"] == "audio_overview"


async def test_fourth_output_at_once_is_busy_and_not_counted(
    quota: QuotaService, user: UUID
) -> None:
    """NB-14: three outputs generate at a time; the fourth raises `BusyError`."""
    running = [new_id() for _ in range(3)]
    for artifact_id in running:
        await quota.reserve(user, ArtifactKind.REPORT, artifact_id)

    with pytest.raises(BusyError) as caught:
        await quota.reserve(user, ArtifactKind.REPORT, new_id())

    assert caught.value.status == 409
    assert caught.value.params == {"what": "artifacts", "limit": 3}
    assert await quota.running_count(user) == 3
    assert (await quota.snapshot(user))["artifacts"].used == 3


async def test_a_finished_output_makes_room_for_the_next_one(
    quota: QuotaService, user: UUID
) -> None:
    """NB-14: `finished` frees the slot, the daily count stays."""
    running = [new_id() for _ in range(3)]
    for artifact_id in running:
        await quota.reserve(user, ArtifactKind.REPORT, artifact_id)

    await quota.finished(user, running[0])
    await quota.reserve(user, ArtifactKind.REPORT, new_id())

    assert await quota.running_count(user) == 3
    assert (await quota.snapshot(user))["artifacts"].used == 4


async def test_limits_are_per_student(quota: QuotaService, user: UUID) -> None:
    """NB-14: another student's outputs do not block this one."""
    for _ in range(3):
        await quota.reserve(new_id(), ArtifactKind.REPORT, new_id())

    await quota.reserve(user, ArtifactKind.REPORT, new_id())

    assert await quota.running_count(user) == 1


async def test_release_gives_a_provider_failure_back(
    quota: QuotaService, user: UUID
) -> None:
    """NB-14: a failed output is not counted in the total or its own counter."""
    artifact_id = new_id()
    await quota.reserve(user, ArtifactKind.SLIDES, artifact_id)

    await quota.finished(user, artifact_id)
    await quota.release(user, ArtifactKind.SLIDES)

    snapshot = await quota.snapshot(user)
    assert (snapshot["artifacts"].used, snapshot["slides"].used) == (0, 0)


async def test_release_never_goes_below_zero(quota: QuotaService, user: UUID) -> None:
    """NB-14: releasing twice, or with nothing counted, leaves zero."""
    await quota.release(user, ArtifactKind.SLIDES)
    artifact_id = new_id()
    await quota.reserve(user, ArtifactKind.REPORT, artifact_id)
    await quota.release(user, ArtifactKind.REPORT)
    await quota.release(user, ArtifactKind.REPORT)

    snapshot = await quota.snapshot(user)
    assert snapshot["artifacts"].used == 0
    assert snapshot["slides"].used == 0
    await quota.reserve(user, ArtifactKind.REPORT, new_id())
    assert (await quota.snapshot(user))["artifacts"].used == 1


async def test_quota_counters_reset_at_midnight_in_tashkent(
    redis: FakeRedis, settings: Settings, user: UUID
) -> None:
    """NB-14: at 00:00 Tashkent the counters of the new day start at zero."""
    clock = FixedClock(LATE)
    service = QuotaService(RedisQuotaStore(redis), clock, settings)
    for _ in range(20):
        artifact_id = new_id()
        await service.reserve(user, ArtifactKind.REPORT, artifact_id)
        await service.finished(user, artifact_id)
    with pytest.raises(QuotaExceededError):
        await service.reserve(user, ArtifactKind.REPORT, new_id())

    clock.advance(minutes=2)
    fresh = await service.snapshot(user)
    await service.reserve(user, ArtifactKind.REPORT, new_id())

    assert fresh["artifacts"].used == 0
    assert fresh["artifacts"].resets_at == datetime(2026, 10, 7, 19, 0, tzinfo=UTC)
    assert (await service.snapshot(user))["artifacts"].used == 1


async def test_started_marks_a_retried_output_as_running_again(
    quota: QuotaService, user: UUID
) -> None:
    """NB-14: a retry or a re-kicked job takes its slot back."""
    artifact_id = new_id()
    await quota.reserve(user, ArtifactKind.REPORT, artifact_id)
    await quota.finished(user, artifact_id)
    assert await quota.running_count(user) == 0

    await quota.started(user, artifact_id)
    await quota.started(user, artifact_id)

    assert await quota.running_count(user) == 1


async def test_clear_running_forgets_one_users_running_set_only(
    quota: QuotaService, user: UUID
) -> None:
    """NB-3, NB-14: used on account deletion; the daily counts are left to expire."""
    stranger = new_id()
    await quota.reserve(user, ArtifactKind.REPORT, new_id())
    await quota.reserve(stranger, ArtifactKind.REPORT, new_id())

    await quota.clear_running(user)
    await quota.clear_running(user)

    assert await quota.running_count(user) == 0
    assert await quota.running_count(stranger) == 1


async def test_redis_keys_expire_after_48_hours(
    redis: FakeRedis, quota: QuotaService, budget: NotebookBudget, user: UUID
) -> None:
    """NB-14: day and quota counters are kept for 48 hours (§ 4.1, Redis keys)."""
    await quota.reserve(user, ArtifactKind.SLIDES, new_id())
    await budget.add(user, 100)

    ttls = [
        await redis.ttl(key)
        async for key in redis.scan_iter(match=f"*{user}*")
        if ":quota:" in key or ":day:" in key
    ]

    assert ttls and all(47 * 3600 < ttl <= 48 * 3600 for ttl in ttls)


# - - - GetUsage - - -


async def test_usage_view_combines_budget_quotas_and_running_outputs(
    redis: FakeRedis, settings: Settings, user: UUID
) -> None:
    """NB-14: `GET /v1/notebooks/usage` as one object."""
    clock = FixedClock(_near_now())
    budget = NotebookBudget(RedisBudgetStore(redis), clock, settings)
    quota = QuotaService(RedisQuotaStore(redis), clock, settings)
    usage = GetUsage(budget, quota, settings)
    await budget.add(user, 1_234)
    await quota.reserve(user, ArtifactKind.INFOGRAPHIC, new_id())
    await quota.reserve(user, ArtifactKind.REPORT, new_id())

    view = await usage.execute(user)

    assert (view.session.used, view.session.limit) == (1_234, 1_500_000)
    assert view.session.resets_at == clock.now() + timedelta(hours=5)
    assert (view.day.used, view.day.limit) == (1_234, 4_000_000)
    assert view.day.resets_at is not None and view.day.resets_at > clock.now()
    assert set(view.quotas) == {"artifacts", "audio_overview", "slides", "infographic"}
    assert (view.quotas["artifacts"].used, view.quotas["artifacts"].limit) == (2, 20)
    assert (view.quotas["infographic"].used, view.quotas["infographic"].limit) == (1, 6)
    assert view.quotas["slides"].used == 0
    assert (view.generating, view.generating_limit) == (2, 3)


async def test_usage_view_of_a_new_student_is_empty(
    redis: FakeRedis, clock: FixedClock, settings: Settings, user: UUID
) -> None:
    """NB-14: no session yet, nothing used, nothing running."""
    usage = GetUsage(
        NotebookBudget(RedisBudgetStore(redis), clock, settings),
        QuotaService(RedisQuotaStore(redis), clock, settings),
        settings,
    )

    view = await usage.execute(user)

    assert view.session.used == view.day.used == 0
    assert view.session.resets_at is None
    assert all(q.used == 0 for q in view.quotas.values())
    assert view.generating == 0
