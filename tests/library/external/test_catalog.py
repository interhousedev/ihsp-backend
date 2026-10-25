"""LIB-12: client + cache + breaker; stale answers when UniLibrary is down."""

from typing import Any

from app.modules.library.domain.enums import ExternalAccess
from app.modules.library.domain.errors import ExternalUnavailableError
from app.modules.library.infrastructure.unilibrary.factory import UniLibraryStack
from app.modules.library.ports.external_catalog import ExternalSearch
from app.modules.library.ports.external_monitor import BreakerState
from tests.fakes.clock import FixedClock
from tests.library.external.conftest import DETAIL_PATH, LIST_PATH
from tests.library.external.support import load

import httpx
import pytest
import respx

FRESH_LIST = 600
FRESH_DETAIL = 86_400
FRESH_TAXONOMY = 604_800
SEARCH = ExternalSearch(q="fizika", field_id=27)


def other_search(n: int) -> ExternalSearch:
    """A search with its own cache key."""
    return ExternalSearch(q=f"query {n}")


# - - - Search - - -


async def test_search_returns_mapped_records_and_paging(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-5, LIB-12: the page of the source as records."""
    upstream.get(LIST_PATH).respond(200, json=load("list_page"))

    page = await stack.catalog.search(SEARCH)

    assert [r.external_id for r in page.records] == ["355186", "896986"]
    assert (page.page, page.last_page, page.total) == (1, 12, 23)
    assert page.stale is False


async def test_search_sends_the_mapped_parameters(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-5: filters reach the source under their own names."""
    route = upstream.get(LIST_PATH).respond(200, json=load("list_page"))

    await stack.catalog.search(
        ExternalSearch(
            q="fizika",
            field_id=27,
            type_id=9,
            language_id=26,
            access=ExternalAccess.OPEN,
            language="en",
        )
    )

    params = route.calls.last.request.url.params
    assert params["name"] == "fizika"
    assert params["resource_field_id"] == "27"
    assert params["resource_type_id"] == "9"
    assert params["resource_language_id"] == "26"
    assert params["resource_modifier_id"] == "1"
    assert params["language"] == "en"
    assert params["resource_category_id"] == "1"


async def test_the_same_search_is_answered_from_the_cache(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: the second identical search makes no request."""
    route = upstream.get(LIST_PATH).respond(200, json=load("list_page"))

    first = await stack.catalog.search(SEARCH)
    second = await stack.catalog.search(SEARCH)

    assert route.call_count == 1
    assert second == first
    stats = await stack.monitor.cache_stats()
    assert (stats.hits, stats.misses) == (1, 1)


async def test_search_cache_is_fresh_for_ten_minutes(
    stack: UniLibraryStack, upstream: respx.MockRouter, clock: FixedClock
) -> None:
    """LIB-12: list answers are fresh for `unilibrary_cache_list_ttl`."""
    route = upstream.get(LIST_PATH).respond(200, json=load("list_page"))
    await stack.catalog.search(SEARCH)

    clock.advance(seconds=FRESH_LIST - 1)
    await stack.catalog.search(SEARCH)
    assert route.call_count == 1

    clock.advance(seconds=1)
    await stack.catalog.search(SEARCH)
    assert route.call_count == 2


async def test_failure_after_expiry_serves_the_old_answer_marked_stale(
    stack: UniLibraryStack, upstream: respx.MockRouter, clock: FixedClock
) -> None:
    """LIB-12: stale-if-error; the UI says "Showing saved results"."""
    upstream.get(LIST_PATH).respond(200, json=load("list_page"))
    fresh = await stack.catalog.search(SEARCH)
    clock.advance(seconds=FRESH_LIST)
    upstream.get(LIST_PATH).respond(500)

    page = await stack.catalog.search(SEARCH)

    assert page.stale is True
    assert page.records == fresh.records
    stats = await stack.monitor.cache_stats()
    assert stats.stale_served == 1


async def test_failure_without_a_cached_answer_is_unavailable(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: nothing to show: `library/external-unavailable` with a wait."""
    upstream.get(LIST_PATH).respond(500)

    with pytest.raises(ExternalUnavailableError) as caught:
        await stack.catalog.search(SEARCH)

    assert caught.value.status == 503
    assert caught.value.params["retry_after"] >= 1


async def test_three_failures_open_the_breaker_and_calls_stop(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: after 3 failures UniLibrary is not called for 60 seconds."""
    route = upstream.get(LIST_PATH).respond(500)
    for n in range(3):
        with pytest.raises(ExternalUnavailableError):
            await stack.catalog.search(other_search(n))
    assert (await stack.monitor.breaker()).state is BreakerState.OPEN

    with pytest.raises(ExternalUnavailableError) as caught:
        await stack.catalog.search(other_search(99))

    assert route.call_count == 3
    assert caught.value.params["retry_after"] == 60


async def test_open_breaker_serves_cached_answers_stale(
    stack: UniLibraryStack, upstream: respx.MockRouter, clock: FixedClock
) -> None:
    """LIB-12: an open breaker answers from the cache, marked stale."""
    upstream.get(LIST_PATH).respond(200, json=load("list_page"))
    await stack.catalog.search(SEARCH)
    clock.advance(seconds=FRESH_LIST + 1)
    route = upstream.get(LIST_PATH).respond(500)
    for n in range(3):
        with pytest.raises(ExternalUnavailableError):
            await stack.catalog.search(other_search(n))
    calls_before = route.call_count

    page = await stack.catalog.search(SEARCH)

    assert page.stale is True
    assert route.call_count == calls_before


async def test_open_breaker_still_gives_fresh_cached_answers_as_fresh(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: a fresh entry is not stale just because the source is down."""
    upstream.get(LIST_PATH).respond(200, json=load("list_page"))
    await stack.catalog.search(SEARCH)
    upstream.get(LIST_PATH).respond(500)
    for n in range(3):
        with pytest.raises(ExternalUnavailableError):
            await stack.catalog.search(other_search(n))

    page = await stack.catalog.search(SEARCH)

    assert page.stale is False


async def test_a_403_counts_towards_the_breaker_and_is_never_retried(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12 / doc 1.2: three 403s open the breaker; no workaround."""
    route = upstream.get(LIST_PATH).respond(
        403, json={"message": "Access denied: unauthorized"}
    )
    for n in range(3):
        with pytest.raises(ExternalUnavailableError):
            await stack.catalog.search(other_search(n))

    status = await stack.monitor.breaker()

    assert status.state is BreakerState.OPEN
    assert route.call_count == 3
    for call in route.calls:
        assert "origin" not in call.request.headers
        assert "referer" not in call.request.headers


async def test_timeouts_count_as_failures(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: three timeouts open the breaker."""
    upstream.get(LIST_PATH).mock(side_effect=httpx.ReadTimeout("slow"))
    for n in range(3):
        with pytest.raises(ExternalUnavailableError):
            await stack.catalog.search(other_search(n))

    assert (await stack.monitor.breaker()).state is BreakerState.OPEN


async def test_after_a_minute_a_probe_goes_out_and_a_good_answer_closes_it(
    stack: UniLibraryStack, upstream: respx.MockRouter, clock: FixedClock
) -> None:
    """LIB-12: the breaker stays open 60 seconds, then tries again."""
    route = upstream.get(LIST_PATH).respond(500)
    for n in range(3):
        with pytest.raises(ExternalUnavailableError):
            await stack.catalog.search(other_search(n))
    clock.advance(seconds=60)
    route.respond(200, json=load("list_page"))

    page = await stack.catalog.search(other_search(50))

    assert page.records
    assert (await stack.monitor.breaker()).state is BreakerState.CLOSED


async def test_retry_after_of_the_source_is_respected(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: a 429 with `Retry-After: 300` holds calls back for 300 seconds."""
    route = upstream.get(LIST_PATH).respond(429, headers={"Retry-After": "300"})
    with pytest.raises(ExternalUnavailableError):
        await stack.catalog.search(other_search(1))

    with pytest.raises(ExternalUnavailableError) as caught:
        await stack.catalog.search(other_search(2))

    assert route.call_count == 1
    assert caught.value.params["retry_after"] == 300


async def test_a_page_of_the_source_that_is_garbage_is_a_failure(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: a 200 without the envelope is not cached as an empty page."""
    upstream.get(LIST_PATH).respond(200, json={"unexpected": True})

    with pytest.raises(ExternalUnavailableError):
        await stack.catalog.search(SEARCH)


# - - - Record - - -


async def test_get_returns_the_detail_with_keywords(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: the record page needs `keywords`, `isbn`, page count."""
    upstream.get(f"{DETAIL_PATH}/355186").respond(200, json=load("detail"))

    record, stale = await stack.catalog.get("355186", category=1, language="uz")

    assert record is not None and record.keywords == (
        "elektronika",
        "sxema",
        "tranzistor",
    )
    assert stale is False


async def test_get_caches_per_language_for_a_day(
    stack: UniLibraryStack, upstream: respx.MockRouter, clock: FixedClock
) -> None:
    """LIB-12: `library:ext:detail:{id}:{lang}`, fresh 24 hours."""
    route = upstream.get(f"{DETAIL_PATH}/355186").respond(200, json=load("detail"))

    await stack.catalog.get("355186", category=1, language="uz")
    await stack.catalog.get("355186", category=1, language="uz")
    await stack.catalog.get("355186", category=1, language="ru")
    assert route.call_count == 2

    clock.advance(seconds=FRESH_DETAIL)
    await stack.catalog.get("355186", category=1, language="uz")
    assert route.call_count == 3


async def test_missing_record_is_none_and_remembered(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: `{"result": []}` means the record is gone; no repeated asking."""
    route = upstream.get(f"{DETAIL_PATH}/7").respond(200, json=load("detail_empty"))

    first = await stack.catalog.get("7", category=1, language="uz")
    second = await stack.catalog.get("7", category=1, language="uz")

    assert first == (None, False)
    assert second == (None, False)
    assert route.call_count == 1


async def test_get_serves_the_old_detail_when_the_source_fails(
    stack: UniLibraryStack, upstream: respx.MockRouter, clock: FixedClock
) -> None:
    """LIB-12: details are stale up to 30 days."""
    upstream.get(f"{DETAIL_PATH}/355186").respond(200, json=load("detail"))
    await stack.catalog.get("355186", category=1, language="uz")
    clock.advance(seconds=FRESH_DETAIL + 1)
    upstream.get(f"{DETAIL_PATH}/355186").respond(502)

    record, stale = await stack.catalog.get("355186", category=1, language="uz")

    assert record is not None and record.external_id == "355186"
    assert stale is True


async def test_get_of_a_non_numeric_id_is_missing_without_a_request(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-12: ids are digits; anything else cannot exist."""
    assert await stack.catalog.get("../x", category=1, language="uz") == (None, False)
    assert upstream.calls.call_count == 0


# - - - Taxonomies - - -


def _mock_taxonomies(upstream: respx.MockRouter) -> dict[str, Any]:
    routes = {
        "resource-types": upstream.get("/api/crm/resource-types/lists").respond(
            200, json=load("taxonomy_types")
        ),
        "resource-fields": upstream.get("/api/crm/resource-fields/lists").respond(
            200, json=load("taxonomy_fields")
        ),
        "resource-languages": upstream.get("/api/crm/resource-languages/lists").respond(
            200, json=load("taxonomy_languages")
        ),
    }
    return routes


async def test_taxonomies_collect_types_fields_and_languages(
    stack: UniLibraryStack, upstream: respx.MockRouter
) -> None:
    """LIB-5: the filter lists, in the user's language, literature types only."""
    _mock_taxonomies(upstream)

    taxonomies = await stack.catalog.taxonomies("en")

    assert [t.name for t in taxonomies.types] == [
        "Textbook",
        "Study manual",
        "Imaginative literature",
    ]
    assert [f.id for f in taxonomies.fields] == [27, 25, 18]
    assert (26, "Latin") in [(x.id, x.name) for x in taxonomies.languages]
    assert taxonomies.stale is False


async def test_taxonomies_are_cached_for_a_week(
    stack: UniLibraryStack, upstream: respx.MockRouter, clock: FixedClock
) -> None:
    """LIB-12: taxonomies are fresh 7 days."""
    routes = _mock_taxonomies(upstream)

    await stack.catalog.taxonomies("uz")
    await stack.catalog.taxonomies("uz")
    assert routes["resource-fields"].call_count == 1

    clock.advance(seconds=FRESH_TAXONOMY)
    await stack.catalog.taxonomies("uz")
    assert routes["resource-fields"].call_count == 2


async def test_taxonomies_are_stale_when_the_source_fails(
    stack: UniLibraryStack, upstream: respx.MockRouter, clock: FixedClock
) -> None:
    """LIB-12: the filters still work during an outage."""
    _mock_taxonomies(upstream)
    await stack.catalog.taxonomies("uz")
    clock.advance(seconds=FRESH_TAXONOMY + 1)
    upstream.get("/api/crm/resource-types/lists").respond(500)

    taxonomies = await stack.catalog.taxonomies("uz")

    assert taxonomies.stale is True
    assert taxonomies.types
