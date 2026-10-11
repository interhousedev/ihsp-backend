"""Local-first web search: stored pages, the query cache, the quota and the Exa merge.

The service is the real one over the real Exa adapter; the Exa client is a stub that
answers the same pages for any query (so a repeat search finds known pages), the pages
are kept in memory and the vectors are the deterministic fake embeddings.
"""

from typing import Any

from app.modules.ai.application.web_pages import WebPageIndex, normalise_query
from app.modules.ai.application.web_search import WebSearchService
from app.modules.ai.infrastructure.exa_search import ExaWebSearch
from app.settings import Settings
from app.shared.actor import Role
from app.shared.clock import local_today
from app.shared.contracts.web_search import WebSearchQuotaError
from app.shared.web_urls import normalise_web_url
from tests.factories import make_actor
from tests.fakes.ai.stores import InMemorySearchQuotaStore
from tests.fakes.ai.uow import FakeAiStore, FakeAiUnitOfWork
from tests.fakes.ai.web_pages import FakeEmbeddingIndex
from tests.fakes.clock import FixedClock

import pytest

PHOTO = "photosynthesis light energy plants"
SITES = ("school1", "school2", "school3")
FIRST_PAGE = "https://school1.example.org/Lesson/"  # the stored spelling of its URL
EXA_URL = "https://school9.example.org/Lesson/#part"


class StubExa:
    """Answers every search with the same pages, in Exa's shape; counts the calls."""

    def __init__(self, sites: tuple[str, ...] = SITES) -> None:
        """Start with the given pages."""
        self.sites = sites
        self.bodies: list[dict[str, Any]] = []

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Return one result per site, about the query."""
        self.bodies.append(body)
        query = body["query"]
        results = [
            {
                "title": f"{query.title()} ({site})",
                "url": f"https://{site}.example.org/Lesson/#part",
                "text": f"{query}: the lesson on {site} explains it step by step.",
                "highlights": [f"{query} is explained on {site}."],
            }
            for site in self.sites
        ]
        return {"results": results, "costDollars": {"total": 0.007}}


class FreeNotes:
    """Collects the zero-cost usage notes of the service."""

    def __init__(self) -> None:
        """Start with none."""
        self.notes: list[tuple[str, str]] = []

    async def note_free(self, *, task: str, model: str) -> None:
        """Remember one note."""
        self.notes.append((task, model))


class Rig:
    """The service with an in-memory page store, a stub Exa and a fixed clock."""

    def __init__(
        self,
        *,
        min_new: int = 2,
        min_similarity: float = 0.3,
        cache_days: int = 183,
        sites: tuple[str, ...] = SITES,
    ) -> None:
        """Wire everything with the given search settings."""
        base = Settings()
        self.settings = base.model_copy(
            update={
                "limits": base.limits.model_copy(
                    update={"web_search_local_min_new": min_new}
                ),
                "exa": base.exa.model_copy(
                    update={
                        "local_min_similarity": min_similarity,
                        "query_cache_days": cache_days,
                    }
                ),
            }
        )
        self.clock = FixedClock()
        self.ai = FakeAiStore()
        self.index = FakeEmbeddingIndex(self.ai.web_pages.vectors)
        self.exa = StubExa(sites)
        self.pages = WebPageIndex(
            uow_factory=lambda: FakeAiUnitOfWork(self.ai),
            embeddings=lambda: self.index,
            clock=self.clock,
            settings=self.settings,
        )
        self.quota = InMemorySearchQuotaStore()
        self.free = FreeNotes()
        self.service = WebSearchService(
            store=self.quota,
            gateway=ExaWebSearch(self.exa, self.settings.web_search, self.settings.exa),
            llm=None,  # type: ignore[arg-type]  # only the deep plan and ranking use it
            clock=self.clock,
            settings=self.settings,
            pages=self.pages,
            usage=self.free,
        )
        self.student = make_actor(Role.STUDENT)

    async def search(self, query: str = PHOTO, **kwargs: Any) -> Any:
        """One chat search of the student."""
        return await self.service.search(
            self.student, query=query, locale="en", kind="chat", **kwargs
        )

    async def used(self) -> int:
        """The student's searches today."""
        return await self.quota.used(self.student.user_id, local_today(self.clock))


async def test_a_search_no_stored_page_can_answer_calls_exa_and_keeps_the_pages() -> (
    None
):
    rig = Rig()

    outcome = await rig.search()

    assert len(rig.exa.bodies) == 1
    assert len(outcome.hits) == 3
    assert outcome.sources == ("exa",)
    assert outcome.cost_micro == 7000
    assert await rig.used() == 1
    stored = rig.ai.web_pages.page(FIRST_PAGE)
    assert stored is not None  # the normalised spelling: lower-case host, no fragment


async def test_stored_pages_are_committed() -> None:
    """Regression: the pages and the cached answer were written but never committed."""
    rig = Rig()
    before = rig.ai.commits

    await rig.search()

    assert rig.ai.commits > before


async def test_enough_new_stored_pages_answer_without_exa_and_without_the_quota() -> (
    None
):
    rig = Rig(min_new=2)
    await rig.search()  # fills the store: Exa, one search

    outcome = await rig.search("how plants use light energy to make food")

    assert len(rig.exa.bodies) == 1  # Exa was not asked again
    assert await rig.used() == 1  # the quota did not move
    assert len(outcome.hits) == 3
    assert outcome.sources == ("local",)
    assert outcome.cost_micro == 0


async def test_known_pages_only_call_exa_and_spend_the_quota() -> None:
    rig = Rig(min_new=2)
    first = await rig.search()
    known = frozenset(normalise_web_url(hit.url) or hit.url for hit in first.hits)

    outcome = await rig.search(known_urls=known)

    assert len(rig.exa.bodies) == 2
    assert await rig.used() == 2
    assert outcome.sources == ("exa",)
    assert rig.ai.web_pages.returned(FIRST_PAGE) == 2  # stored once, returned twice


async def test_a_repeat_of_the_same_query_is_a_cache_hit_at_no_cost() -> None:
    rig = Rig(min_new=2, min_similarity=0.99)  # the vectors alone would not match
    await rig.search()

    outcome = await rig.search("  Photosynthesis LIGHT energy plants?  ")

    assert len(rig.exa.bodies) == 1
    assert await rig.used() == 1
    assert len(outcome.hits) == 3
    assert outcome.sources == ("cache",)


def test_queries_are_compared_without_case_spacing_or_end_punctuation() -> None:
    assert normalise_query("  Photosynthesis, LIGHT energy plants?  ") == (
        "photosynthesis, light energy plants"
    )


async def test_below_the_similarity_threshold_nothing_is_local() -> None:
    rig = Rig(min_new=2, min_similarity=0.99, cache_days=0)
    await rig.search()

    outcome = await rig.search("how plants use light energy to make food")

    assert len(rig.exa.bodies) == 2
    assert outcome.sources == ("exa",)


async def test_fewer_new_matches_than_the_minimum_call_exa() -> None:
    rig = Rig(min_new=4)  # only three pages exist
    await rig.search()

    await rig.search("how plants use light energy to make food")

    assert len(rig.exa.bodies) == 2


async def test_a_minimum_of_zero_always_asks_exa() -> None:
    rig = Rig(min_new=0)
    await rig.search()

    outcome = await rig.search()

    assert len(rig.exa.bodies) == 2
    assert outcome.sources == ("exa",)


async def test_exa_pages_come_first_and_the_stored_new_ones_fill_up() -> None:
    rig = Rig(min_new=3, cache_days=0)  # two new stored pages are not enough
    await rig.search()  # three stored pages
    rig.exa.sites = ("school9",)  # Exa now finds one new page only
    known = frozenset({FIRST_PAGE})

    outcome = await rig.search(
        "how plants use light energy to make food", known_urls=known
    )

    urls = [hit.url for hit in outcome.hits]
    assert urls[0] == EXA_URL
    assert FIRST_PAGE not in [normalise_web_url(url) for url in urls]
    assert len(urls) == len({normalise_web_url(url) for url in urls})
    assert outcome.sources == ("exa", "local")


async def test_the_same_page_twice_in_one_answer_is_stored_once() -> None:
    rig = Rig(sites=("school1", "school1"))  # Exa repeats one page in its answer

    await rig.search()

    assert len(rig.ai.web_pages.rows) == 1


async def test_an_exhausted_quota_still_answers_from_the_stored_pages() -> None:
    rig = Rig(min_new=2)
    await rig.search()
    limit = rig.settings.limits.web_search_per_day_student
    for _ in range(limit):
        await rig.quota.add(rig.student.user_id, local_today(rig.clock), 1)

    outcome = await rig.search("how plants use light energy to make food")

    assert outcome.sources == ("local",)
    with pytest.raises(WebSearchQuotaError):
        await rig.search("another question about volcanoes and lava")


async def test_the_daily_purge_keeps_a_page_seen_again() -> None:
    rig = Rig(min_new=2)
    await rig.search()  # three pages and one answer, on day 0
    rig.clock.advance(days=100)
    rig.exa.sites = ("school1",)
    await rig.search("volcano lava rocks")  # Exa returns school1 again on day 100
    rig.clock.advance(
        days=100
    )  # day 200: two pages and day 0's answer are past 183 days

    report = await rig.pages.purge()

    assert report.pages == 2
    assert report.queries == 1
    assert rig.ai.web_pages.page(FIRST_PAGE) is not None
    assert rig.ai.web_pages.page("https://school2.example.org/Lesson/") is None


async def test_answers_without_exa_are_noted_as_free_usage() -> None:
    rig = Rig(min_new=2, min_similarity=0.99)
    await rig.search()
    assert rig.free.notes == []  # a paid search is recorded by the gateway decorator

    await rig.search("  Photosynthesis LIGHT energy plants?  ")  # the query cache

    assert rig.free.notes == [("web_search", "cache")]
    assert len(rig.exa.bodies) == 1


async def test_pages_found_by_meaning_are_noted_as_local_usage() -> None:
    rig = Rig(min_new=2)
    await rig.search()

    await rig.search("how plants use light energy to make food")

    assert rig.free.notes == [("web_search", "local")]
