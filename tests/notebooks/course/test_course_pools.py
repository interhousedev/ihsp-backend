"""LMS-AI 3.3: the Redis keys and limits of the course staff pool."""

from datetime import date, timedelta

from app.modules.notebooks.application.budget import NotebookBudget
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.infrastructure.redis_budget_store import RedisBudgetStore
from app.modules.notebooks.infrastructure.redis_quota_store import RedisQuotaStore
from app.settings import Settings
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

from fakeredis.aioredis import FakeRedis


async def test_the_course_budget_uses_the_keys_of_the_author_assistant(
    redis: FakeRedis, clock: FixedClock
) -> None:
    """LMS-AI 3.3: `ai:lms:session:{user}` and `ai:lms:day:{user}:{date}`."""
    store = RedisBudgetStore(redis, prefix="ai:lms")
    user = new_id()

    await store.open_session(user, clock.now() + timedelta(hours=5))
    await store.add_session(user, 7)
    await store.add_day(user, date(2026, 10, 9), 7)

    keys = sorted([str(key) async for key in redis.scan_iter("ai:*")])
    assert keys == [f"ai:lms:day:{user}:2026-10-09", f"ai:lms:session:{user}"]


async def test_the_course_quota_has_its_own_keys(redis: FakeRedis) -> None:
    """LMS-AI 3.3: `lms:quota:*` and `lms:running:*` next to the `nb:*` ones."""
    store = RedisQuotaStore(redis, prefix="lms")
    user, artifact = new_id(), new_id()

    await store.add(user, date(2026, 10, 9), "artifacts")
    await store.add_running(user, artifact)

    keys = sorted([str(key) async for key in redis.scan_iter("*")])
    assert keys == [
        f"lms:quota:{user}:2026-10-09:artifacts",
        f"lms:running:{user}",
    ]


async def test_a_pool_picks_the_course_pool_only_for_workspaces(
    redis: FakeRedis, clock: FixedClock, settings: Settings
) -> None:
    """LMS-AI 3.3: `pool(course)`; without a course pool everything stays put."""
    course = NotebookBudget(RedisBudgetStore(redis), clock, settings, for_course=True)
    student = NotebookBudget(RedisBudgetStore(redis), clock, settings, course=course)
    alone = NotebookBudget(RedisBudgetStore(redis), clock, settings)

    assert (student.pool(True), student.pool(False)) == (course, student)
    assert alone.pool(True) is alone
    user = new_id()
    assert (await course.usage(user)).day.limit is None  # course staff: not limited
    assert (
        await student.usage(user)
    ).session.limit == settings.limits.nb_session_tokens_student


async def test_the_course_quota_counts_all_outputs_and_is_unlimited_for_staff(
    redis: FakeRedis, clock: FixedClock, settings: Settings
) -> None:
    """LMS-AI 3.3: the course pool is counted; staff have no cap on it."""
    quota = QuotaService(RedisQuotaStore(redis), clock, settings, for_course=True)

    counts = await quota.snapshot(new_id())

    assert counts["artifacts"].limit is None
    assert counts[ArtifactKind.SLIDES.value].limit is None
