"""NB-31, NB-33: the web search quota, the feature switch and the fast/deep runs."""

import asyncio
from datetime import UTC, datetime
from typing import Any

from app.modules.ai.application.web_search import WebSearchService
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.ai_tasks import AiTask
from app.shared.contracts.ai import AiProviderError
from app.shared.contracts.web_search import (
    SearchReply,
    WebSearchDisabledError,
    WebSearchQuotaError,
    WebSearchUnavailableError,
)
from tests.factories import make_actor
from tests.fakes.ai.stores import InMemorySearchQuotaStore
from tests.fakes.ai.web_search import ScriptedJson, ScriptedWebSearch, page
from tests.fakes.clock import FixedClock

import pytest


class Rig:
    """The service over a scripted search, a scripted JSON model and a counter."""

    def __init__(self, settings: Settings, clock: FixedClock) -> None:
        """Wire the service."""
        self.search = ScriptedWebSearch()
        self.json = ScriptedJson()
        self.store = InMemorySearchQuotaStore()
        self.clock = clock
        self.service = WebSearchService(
            store=self.store,
            gateway=self.search,
            llm=self.json,  # type: ignore[arg-type]
            clock=clock,
            settings=settings,
        )
        self.student = make_actor(Role.STUDENT)
        self.teacher = make_actor(Role.TEACHER)


def make_rig(
    clock: FixedClock,
    *,
    limits: dict[str, Any] | None = None,
    features: dict[str, bool] | None = None,
) -> Rig:
    """A rig with the default settings, optionally changed."""
    base = Settings()
    updates: dict[str, Any] = {}
    if limits:
        updates["limits"] = base.limits.model_copy(update=limits)
    if features:
        updates["features"] = base.features.model_copy(update=features)
    return Rig(base.model_copy(update=updates), clock)


@pytest.fixture
def clock() -> FixedClock:
    """2026-10-06 09:00 UTC, which is 14:00 in Tashkent."""
    return FixedClock()


# - - - the quota - - -


async def test_a_chat_search_spends_one_of_ten_and_says_so(clock: FixedClock) -> None:
    """NB-33: "3 of 10 searches left today" comes from this quota."""
    rig = make_rig(clock)

    outcome = await rig.service.search(rig.student, query="photosynthesis", locale="en")

    assert len(outcome.hits) == 3
    assert (outcome.quota.used, outcome.quota.limit, outcome.quota.remaining) == (
        1,
        10,
        9,
    )
    assert outcome.quota.resets_at == datetime(2026, 10, 6, 19, 0, tzinfo=UTC)  # 00:00
    assert outcome.quota.max_results == 5


async def test_the_search_uses_the_cheap_task_model_and_the_blocklist(
    clock: FixedClock,
) -> None:
    """NB-31: the call carries the task's profile, the language and the blocklist."""
    rig = make_rig(clock)

    await rig.service.search(
        rig.student, query="  photosynthesis\n basics ", locale="uz"
    )

    call = rig.search.calls[0]
    assert call.query == "photosynthesis basics"
    assert call.language == "uz"
    assert call.profile.task is AiTask.WEB_SEARCH
    assert call.explain is False
    assert call.max_results == 5
    assert "pornhub.com" in call.exclude_domains


async def test_students_and_staff_have_their_own_daily_limits(
    clock: FixedClock,
) -> None:
    """NB-33: LIMITS__WEB_SEARCH_PER_DAY_STUDENT (10) and _STAFF (30)."""
    rig = make_rig(clock)

    assert (await rig.service.quota(rig.student)).limit == 10
    assert (await rig.service.quota(rig.teacher)).limit == 30


async def test_the_search_after_the_last_one_is_refused_and_not_run(
    clock: FixedClock,
) -> None:
    """NB-33: quota exhaustion is a 429 with the reset time; nothing is searched."""
    rig = make_rig(clock, limits={"web_search_per_day_student": 2})
    await rig.service.search(rig.student, query="one", locale="en")
    await rig.service.search(rig.student, query="two", locale="en")

    with pytest.raises(WebSearchQuotaError) as caught:
        await rig.service.search(rig.student, query="three", locale="en")

    assert caught.value.status == 429
    assert caught.value.code == "web-search/quota-exceeded"
    assert caught.value.params["limit"] == 2
    assert caught.value.params["left"] == 0
    assert caught.value.params["resets_at"] == "2026-10-06T19:00:00+00:00"
    assert len(rig.search.calls) == 2
    assert (await rig.service.quota(rig.student)).used == 2


async def test_the_quota_starts_again_at_midnight_in_tashkent(
    clock: FixedClock,
) -> None:
    """NB-33: the day is the Tashkent date."""
    rig = make_rig(clock, limits={"web_search_per_day_student": 1})
    await rig.service.search(rig.student, query="one", locale="en")
    clock.advance(hours=10)  # 00:00 in Tashkent

    outcome = await rig.service.search(rig.student, query="two", locale="en")

    assert outcome.quota.used == 1


async def test_two_requests_at_once_cannot_both_take_the_last_search(
    clock: FixedClock,
) -> None:
    """NB-33: the counter is taken atomically before the search."""
    rig = make_rig(clock, limits={"web_search_per_day_student": 1})

    results = await asyncio.gather(
        rig.service.search(rig.student, query="a", locale="en"),
        rig.service.search(rig.student, query="b", locale="en"),
        return_exceptions=True,
    )

    assert sum(isinstance(r, WebSearchQuotaError) for r in results) == 1
    assert len(rig.search.calls) == 1


async def test_the_quota_of_one_student_is_not_the_quota_of_another(
    clock: FixedClock,
) -> None:
    rig = make_rig(clock, limits={"web_search_per_day_student": 1})
    other = make_actor(Role.STUDENT)
    await rig.service.search(rig.student, query="a", locale="en")

    outcome = await rig.service.search(other, query="a", locale="en")

    assert outcome.quota.used == 1


# - - - the switch - - -


async def test_with_the_feature_off_nothing_is_searched_or_counted(
    clock: FixedClock,
) -> None:
    """NB-32: FEATURES__WEB_SEARCH=false answers web-search/disabled."""
    rig = make_rig(clock, features={"web_search": False})

    with pytest.raises(WebSearchDisabledError) as caught:
        await rig.service.search(rig.student, query="a", locale="en")

    assert caught.value.status == 404
    assert rig.search.calls == []
    assert rig.store.days == {}
    status = await rig.service.quota(rig.student)
    assert status.enabled is False


async def test_a_zero_limit_switches_the_search_off_for_that_role(
    clock: FixedClock,
) -> None:
    """NB-33: LIMITS__WEB_SEARCH_PER_DAY_STUDENT=0 forbids web search."""
    rig = make_rig(clock, limits={"web_search_per_day_student": 0})

    with pytest.raises(WebSearchDisabledError):
        await rig.service.search(rig.student, query="a", locale="en")

    assert (await rig.service.quota(rig.student)).enabled is False
    assert (await rig.service.quota(rig.teacher)).enabled is True


async def test_a_provider_failure_gives_the_search_back(clock: FixedClock) -> None:
    """NB-33: a search that did not happen is not counted."""
    rig = make_rig(clock)
    rig.search.fail_next()

    with pytest.raises(WebSearchUnavailableError) as caught:
        await rig.service.search(rig.student, query="a", locale="en")

    assert caught.value.status == 503
    assert (await rig.service.quota(rig.student)).used == 0


# - - - fast and deep - - -


async def test_a_fast_search_is_one_call_with_reasons_and_more_results(
    clock: FixedClock,
) -> None:
    """NB-31: fast = one search call; the model gives a reason per page."""
    rig = make_rig(clock)

    outcome = await rig.service.search(
        rig.student, query="photosynthesis", locale="ru", kind="fast"
    )

    assert len(rig.search.calls) == 1
    call = rig.search.calls[0]
    assert (call.profile.task, call.explain, call.max_results) == (
        AiTask.DISCOVER,
        True,
        8,
    )
    assert outcome.queries == ("photosynthesis",)
    assert all(hit.why for hit in outcome.hits)
    assert outcome.quota.used == 1
    assert rig.json.requests == []


async def test_a_deep_search_plans_searches_several_times_and_ranks(
    clock: FixedClock,
) -> None:
    """NB-31: deep = a plan, one search per query, one ranking; it costs 3."""
    rig = make_rig(clock)
    rig.json.push(
        {"queries": ["photosynthesis stages", "фотосинтез", "calvin cycle", "extra"]},
        {
            "results": [
                {"index": 4, "why": "Official explanation."},
                {"index": 0, "why": "Good first read."},
                {"index": 99, "why": "No such page."},
                {"index": 4, "why": "Repeated page."},
                {"index": "x", "why": "Bad number."},
            ]
        },
    )

    outcome = await rig.service.search(
        rig.student, query="photosynthesis", locale="en", kind="deep"
    )

    assert outcome.queries == ("photosynthesis", "photosynthesis stages", "фотосинтез")
    assert len(rig.search.calls) == 3
    assert {call.query for call in rig.search.calls} == set(outcome.queries)
    assert [hit.url for hit in outcome.hits] == [
        "https://school5.example.org/photosynthesis",
        "https://school1.example.org/photosynthesis",
    ]
    assert [hit.why for hit in outcome.hits] == [
        "Official explanation.",
        "Good first read.",
    ]
    assert outcome.quota.used == 3
    assert len(rig.json.requests) == 2


async def test_a_deep_search_needs_all_its_searches_left(clock: FixedClock) -> None:
    """NB-33: with 2 left a deep search (3) is refused and nothing is spent."""
    rig = make_rig(clock, limits={"web_search_per_day_student": 5})
    await rig.service.search(rig.student, query="a", locale="en")
    await rig.service.search(rig.student, query="b", locale="en")
    await rig.service.search(rig.student, query="c", locale="en")

    with pytest.raises(WebSearchQuotaError) as caught:
        await rig.service.search(rig.student, query="d", locale="en", kind="deep")

    assert caught.value.params["needed"] == 3
    assert caught.value.params["left"] == 2
    assert (await rig.service.quota(rig.student)).used == 3


async def test_a_deep_search_survives_one_failed_search(clock: FixedClock) -> None:
    rig = make_rig(clock)
    rig.json.push({"queries": ["b", "c"]}, {"results": [{"index": 0, "why": "ok"}]})
    rig.search.push(
        SearchReply(hits=(page(1),), usage={}),
        WebSearchUnavailableError(),
        SearchReply(hits=(page(2),), usage={}),
    )

    outcome = await rig.service.search(rig.student, query="a", locale="en", kind="deep")

    assert len(outcome.hits) == 1


async def test_a_deep_search_with_no_search_working_gives_everything_back(
    clock: FixedClock,
) -> None:
    rig = make_rig(clock)
    rig.json.push({"queries": ["b", "c"]})
    rig.search.push(*[WebSearchUnavailableError() for _ in range(3)])

    with pytest.raises(WebSearchUnavailableError):
        await rig.service.search(rig.student, query="a", locale="en", kind="deep")

    assert (await rig.service.quota(rig.student)).used == 0


async def test_a_deep_search_still_works_when_the_planner_and_ranker_fail(
    clock: FixedClock,
) -> None:
    """The plan and the ranking are best effort; the pages of the search remain."""
    rig = make_rig(clock)
    rig.json.push(AiProviderError(support_details="down"), AiProviderError())

    outcome = await rig.service.search(rig.student, query="a", locale="en", kind="deep")

    assert outcome.queries == ("a",)
    assert len(outcome.hits) == 3  # the pages of the single search, in order
    assert outcome.quota.used == 3  # the deep price is paid anyway


async def test_the_same_page_from_two_searches_is_listed_once(
    clock: FixedClock,
) -> None:
    rig = make_rig(clock)
    rig.json.push(
        {"queries": ["b"]}, {"results": [{"index": i, "why": "w"} for i in range(5)]}
    )
    rig.search.push(
        SearchReply(hits=(page(1), page(2)), usage={}),
        SearchReply(hits=(page(2), page(3)), usage={}),
    )

    outcome = await rig.service.search(rig.student, query="a", locale="en", kind="deep")

    assert [hit.site for hit in outcome.hits] == [
        "school1.example.org",
        "school2.example.org",
        "school3.example.org",
    ]
    assert isinstance(rig.student, Actor)
