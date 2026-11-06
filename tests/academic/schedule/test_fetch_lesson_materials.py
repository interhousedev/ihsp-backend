"""A3: the worker's one-lesson EMIS fetch and the state it shares in Redis."""

import datetime as dt
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from app.modules.academic.application.schedule.fetch_lesson_materials import (
    FetchLessonMaterials,
)
from app.modules.academic.infrastructure.schedule.lesson_fetch_store import (
    MAX_RUNNING_PER_USER,
    NEGATIVE_TTL_SECONDS,
    RedisLessonFetchStore,
)
from app.shared.contracts.emis import EmisAuthFailed, EmisPaused
from app.shared.contracts.mcp_academic import MaterialFetch
from tests.fakes.clock import FixedClock

import pytest
from fakeredis.aioredis import FakeRedis

NOW = dt.datetime(2026, 10, 7, 9, 0, tzinfo=dt.UTC)  # a Wednesday
MONDAY = dt.date(2026, 10, 5)
TERM = SimpleNamespace(
    id=uuid4(),
    academic_year="2026-2027",
    half=1,
    starts_on=dt.date(2026, 9, 2),
    ends_on=dt.date(2026, 12, 25),
    contains=lambda day: dt.date(2026, 9, 2) <= day <= dt.date(2026, 12, 25),
)


class Uow:
    def __init__(self, lesson: Any, group_id: UUID) -> None:
        self.lessons = SimpleNamespace(get=self._lesson)
        self.students = SimpleNamespace(get=self._student)
        self.terms = SimpleNamespace(list_all=self._terms)
        self.lesson = lesson
        self.group_id = group_id

    async def __aenter__(self) -> "Uow":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def _lesson(self, lesson_id: UUID) -> Any:
        return self.lesson

    async def _student(self, user_id: UUID) -> Any:
        return SimpleNamespace(group_id=self.group_id, subgroup=None)

    async def _terms(self) -> list[Any]:
        return [TERM]


class Emis:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[dt.date, dt.date]] = []

    async def timetable(self, user_id: UUID, begin: dt.date, end: dt.date) -> list[Any]:
        self.calls.append((begin, end))
        if self.error:
            raise self.error
        return ["class"]


class Sync:
    def __init__(self, added: int) -> None:
        self.added = added
        self.calls: list[dict[str, Any]] = []

    async def apply_lesson_materials(self, **kwargs: Any) -> int:
        self.calls.append(kwargs)
        return self.added


def _build(
    *,
    day: dt.date = MONDAY,
    emis: Emis | None = None,
    sync: Sync | None = None,
) -> tuple[Any, ...]:
    lesson_id, user_id = uuid4(), uuid4()
    lesson = SimpleNamespace(id=lesson_id, date=day)
    store = RedisLessonFetchStore(FakeRedis(decode_responses=True))
    emis = emis or Emis()
    sync = sync or Sync(1)
    use_case = FetchLessonMaterials(
        uow_factory=lambda: Uow(lesson, uuid4()),  # type: ignore[arg-type,return-value]
        emis=emis,  # type: ignore[arg-type]
        sync=sync,
        store=store,
        clock=FixedClock(NOW),
    )
    return use_case, store, emis, sync, lesson_id, user_id


async def _run(use_case: Any, store: Any, lesson_id: UUID, user_id: UUID) -> Any:
    begun = MaterialFetch(job_id="j" * 32, status="running", started_at=NOW)
    await store.begin(lesson_id, user_id, begun)
    await use_case.execute(lesson_id, user_id, "j" * 32)
    return await store.get(lesson_id)


async def test_asks_one_school_week_and_imports_only_this_lesson() -> None:
    """A3: one Monday-to-Sunday request, restricted to the lesson."""
    use_case, store, emis, sync, lesson_id, user_id = _build()

    state = await _run(use_case, store, lesson_id, user_id)

    assert state.status == "done"
    assert emis.calls == [(dt.date(2026, 10, 5), dt.date(2026, 10, 11))]
    assert sync.calls[0]["lesson_id"] == lesson_id
    assert sync.calls[0]["user_id"] == user_id


async def test_nothing_in_emis_still_ends_done() -> None:
    """A3: the tool reads this as none; nothing is purged by this path."""
    use_case, store, _, _, lesson_id, user_id = _build(sync=Sync(0))
    assert (await _run(use_case, store, lesson_id, user_id)).status == "done"


async def test_an_expired_emis_login_is_reauth() -> None:
    """A3: fixed reason, no import."""
    sync = Sync(1)
    use_case, store, _, _, lesson_id, user_id = _build(
        emis=Emis(EmisAuthFailed()), sync=sync
    )
    state = await _run(use_case, store, lesson_id, user_id)
    assert (state.status, state.reason) == ("failed", "emis_reauth")
    assert sync.calls == []


async def test_a_global_pause_ends_at_once_as_busy() -> None:
    """A3: EMIS asked for a rest: no wait, no import."""
    sync = Sync(1)
    use_case, store, _, _, lesson_id, user_id = _build(
        emis=Emis(EmisPaused(retry_after=60)), sync=sync
    )
    state = await _run(use_case, store, lesson_id, user_id)
    assert (state.status, state.reason) == ("failed", "emis_busy")
    assert sync.calls == []


async def test_a_lesson_of_an_old_term_does_not_ask_emis() -> None:
    """A3: outside the current term: EMIS is not asked."""
    use_case, store, emis, _, lesson_id, user_id = _build(day=dt.date(2026, 3, 2))
    state = await _run(use_case, store, lesson_id, user_id)
    assert (state.status, state.reason) == ("done", "old_term")
    assert emis.calls == []


async def test_an_unexpected_failure_never_leaves_it_running() -> None:
    """A3: a crash in the import ends as busy."""

    class Broken(Sync):
        async def apply_lesson_materials(self, **kwargs: Any) -> int:
            raise RuntimeError("boom")

    use_case, store, _, _, lesson_id, user_id = _build(sync=Broken(0))
    state = await _run(use_case, store, lesson_id, user_id)
    assert (state.status, state.reason) == ("failed", "emis_busy")


async def test_two_callers_share_one_job() -> None:
    """A3: the second begin gets the first job."""
    store = RedisLessonFetchStore(FakeRedis(decode_responses=True))
    lesson_id = uuid4()
    first = MaterialFetch(job_id="1" * 32, status="running", started_at=NOW)
    second = MaterialFetch(job_id="2" * 32, status="running", started_at=NOW)

    assert await store.begin(lesson_id, uuid4(), first) == first
    assert await store.begin(lesson_id, uuid4(), second) == first


async def test_a_user_runs_at_most_three_fetches() -> None:
    """A3: the fourth lesson is refused until one ends."""
    store = RedisLessonFetchStore(FakeRedis(decode_responses=True))
    user_id = uuid4()
    lessons = [uuid4() for _ in range(MAX_RUNNING_PER_USER + 1)]
    fetch = MaterialFetch(job_id="1" * 32, status="running", started_at=NOW)

    for lesson_id in lessons[:-1]:
        assert await store.begin(lesson_id, user_id, fetch) == fetch
    assert await store.begin(lessons[-1], user_id, fetch) is None

    done = MaterialFetch(job_id="1" * 32, status="done", started_at=NOW)
    await store.finish(lessons[0], user_id, done)
    assert await store.begin(lessons[-1], user_id, fetch) == fetch


async def test_done_is_kept_as_the_negative_cache() -> None:
    """A3: an empty answer is remembered for six hours."""
    redis = FakeRedis(decode_responses=True)
    store = RedisLessonFetchStore(redis)
    lesson_id, user_id = uuid4(), uuid4()
    fetch = MaterialFetch(job_id="1" * 32, status="running", started_at=NOW)
    await store.begin(lesson_id, user_id, fetch)
    await store.finish(
        lesson_id,
        user_id,
        MaterialFetch(job_id="1" * 32, status="done", started_at=NOW),
    )
    ttl = await redis.ttl(f"mcp:matfetch:{lesson_id}")
    assert NEGATIVE_TTL_SECONDS - 5 <= ttl <= NEGATIVE_TTL_SECONDS


async def test_a_stale_job_does_not_overwrite_a_newer_one() -> None:
    """A3: only the job in the state may finish it."""
    store = RedisLessonFetchStore(FakeRedis(decode_responses=True))
    lesson_id, user_id = uuid4(), uuid4()
    new = MaterialFetch(job_id="2" * 32, status="running", started_at=NOW)
    await store.begin(lesson_id, user_id, new)
    await store.finish(
        lesson_id,
        user_id,
        MaterialFetch(job_id="1" * 32, status="done", started_at=NOW),
    )
    assert await store.get(lesson_id) == new


@pytest.mark.parametrize("reason", ["emis_reauth", "emis_busy"])
async def test_a_failure_is_read_back(reason: Any) -> None:
    """A3: the reason survives the round trip."""
    store = RedisLessonFetchStore(FakeRedis(decode_responses=True))
    lesson_id, user_id = uuid4(), uuid4()
    fetch = MaterialFetch(
        job_id="1" * 32, status="failed", started_at=NOW, reason=reason
    )
    begun = MaterialFetch(job_id="1" * 32, status="running", started_at=NOW)
    await store.begin(lesson_id, user_id, begun)
    await store.finish(lesson_id, user_id, fetch)
    assert await store.get(lesson_id) == fetch
