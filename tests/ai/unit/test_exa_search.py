"""Exa web search: the request, the answer, the errors and the key (NB-31, NB-33).

The HTTP calls go through respx (no network); the adapter sees answers from a stub
client, so every platform error is checked without a server.
"""

import json
from typing import Any

from app.modules.ai.infrastructure.exa import ExaCallError, ExaClient
from app.modules.ai.infrastructure.exa_rate_limit import LimitedExa
from app.modules.ai.infrastructure.exa_search import (
    ExaWebSearch,
    cost_micro_of,
    search_body,
)
from app.modules.ai.infrastructure.fake_exa import FakeExaClient
from app.modules.ai.infrastructure.gateway_factory import make_web_search_gateway
from app.settings import ExaSettings, Settings
from app.settings_web_search import WebSearchSettings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.web_search import (
    SearchCall,
    WebSearchBusyError,
    WebSearchUnavailableError,
)

import httpx
import pytest
import respx
from fakeredis.aioredis import FakeRedis
from pydantic import SecretStr
from structlog.testing import capture_logs

KEY = "exa-key-for-tests-only"
URL = "https://api.exa.ai/search"
QUERY = "why is the sky blue"


class StubExa:
    """Answers one search with the given object, or raises the given error."""

    def __init__(self, answer: dict[str, Any] | ExaCallError) -> None:
        """Keep the answer and the bodies it was asked with."""
        self.answer = answer
        self.bodies: list[dict[str, Any]] = []

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Record the body and answer."""
        self.bodies.append(body)
        if isinstance(self.answer, ExaCallError):
            raise self.answer
        return self.answer


def call(
    *,
    explain: bool = True,
    max_results: int = 5,
    exclude: tuple[str, ...] = (),
) -> SearchCall:
    """A search call the way the service makes it."""
    return SearchCall(
        query=QUERY,
        language="en",
        max_results=max_results,
        explain=explain,
        profile=Settings().ai_profile(AiTask.DISCOVER),
        exclude_domains=exclude,
    )


def page(n: int, **fields: Any) -> dict[str, Any]:
    """One result of an Exa answer."""
    item: dict[str, Any] = {
        "title": f"Page {n}",
        "url": f"https://school{n}.example.org/sky",
        "text": f"Text of page {n}.",
        "highlights": [f"Highlight {n} sentence."],
        "highlightScores": [0.9],
    }
    item.update(fields)
    return item


def gateway(answer: Any, config: WebSearchSettings | None = None) -> ExaWebSearch:
    """The adapter over a stub answer, with the default settings."""
    return ExaWebSearch(StubExa(answer), config or WebSearchSettings(), ExaSettings())


# - - - the request - - -


def test_the_body_asks_for_text_and_highlights_only_when_explained() -> None:
    config = ExaSettings(text_max_characters=900)

    chat = search_body(call(explain=False), config)
    assert chat == {
        "query": QUERY,
        "type": "auto",
        "numResults": 5,
        "contents": {"text": {"maxCharacters": 900}},
    }

    fast = search_body(call(explain=True), config)
    assert fast["contents"]["highlights"] == {
        "numSentences": 2,
        "highlightsPerUrl": 2,
        "query": QUERY,
    }


def test_blocked_domains_go_as_exclude_domains_once_each() -> None:
    body = search_body(call(exclude=("a.org", "b.org", "a.org")), ExaSettings())

    assert body["excludeDomains"] == ["a.org", "b.org"]
    assert "excludeDomains" not in search_body(call(), ExaSettings())


@respx.mock
async def test_the_key_goes_in_the_header_and_never_in_the_body() -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200, json={"results": [], "costDollars": {"total": 0.007}}
        )
    )
    client = ExaClient(api_key=KEY, base_url="https://api.exa.ai", timeout_seconds=5)

    data = await client.search(search_body(call(), ExaSettings()))
    await client.aclose()

    request = route.calls.last.request
    assert request.headers["x-api-key"] == KEY
    assert KEY.encode() not in request.content
    assert str(request.url) == URL
    assert json.loads(request.content)["query"] == QUERY
    assert data["costDollars"] == {"total": 0.007}


# - - - the answer - - -


async def test_hits_take_the_first_highlight_as_the_reason() -> None:
    answer = {
        "results": [page(1), page(2, highlights=["Second page reason.", "More."])],
        "costDollars": {"total": 0.017},
    }

    reply = await gateway(answer).search(call())

    assert [hit.url for hit in reply.hits] == [
        "https://school1.example.org/sky",
        "https://school2.example.org/sky",
    ]
    first = reply.hits[0]
    assert first.title == "Page 1"
    assert first.site == "school1.example.org"
    assert first.snippet == "Text of page 1."
    assert first.why == "Highlight 1 sentence."
    assert reply.hits[1].why == "Second page reason."
    assert reply.cost_micro == 17000
    assert reply.notice is None


async def test_a_chat_hit_has_no_reason_and_no_text_means_the_highlights() -> None:
    answer = {
        "results": [page(1), page(2, text="")],
        "costDollars": {"total": 0.007},
    }

    reply = await gateway(answer).search(call(explain=False))

    assert [hit.why for hit in reply.hits] == ["", ""]
    assert reply.hits[1].snippet == "Highlight 2 sentence."


async def test_bad_blocked_and_repeated_pages_are_dropped() -> None:
    answer = {
        "results": [
            page(1),
            page(1),  # the same page again
            page(2, url="https://www.pornhub.com/x"),  # blocked by default
            page(3, url="ftp://school3.example.org/sky"),  # not a web page
            page(4, url=""),  # no site
            "not an object",
            page(5),
        ],
        "costDollars": {"total": 0.0},
    }

    reply = await gateway(answer).search(call(max_results=2))
    assert [hit.site for hit in reply.hits] == [
        "school1.example.org",
        "school5.example.org",
    ]

    excluded = await gateway(answer).search(
        call(max_results=3, exclude=("school5.example.org",))
    )
    assert [hit.site for hit in excluded.hits] == ["school1.example.org"]


def test_the_charge_is_micro_dollars_and_a_missing_charge_is_zero() -> None:
    assert cost_micro_of({"costDollars": {"total": 0.007}}) == 7000
    assert cost_micro_of({}) == 0
    assert cost_micro_of({"costDollars": {"total": "0.007"}}) == 0
    assert cost_micro_of({"costDollars": {"total": -1}}) == 0
    assert cost_micro_of({"costDollars": {"total": True}}) == 0


# - - - errors - - -


async def test_a_timeout_is_an_empty_reply_with_a_notice_and_a_log_line() -> None:
    with capture_logs() as logs:
        reply = await gateway(ExaCallError(timeout=True)).search(call())

    assert reply.hits == ()
    assert reply.notice == "timeout"
    assert reply.cost_micro == 0
    assert any(entry["event"] == "web_search_timeout" for entry in logs)


@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_key_is_logged_and_is_an_unavailable_search(
    status: int,
) -> None:
    with capture_logs() as logs:
        with pytest.raises(WebSearchUnavailableError) as raised:
            await gateway(ExaCallError(status=status, details="bad key")).search(call())

    assert type(raised.value) is WebSearchUnavailableError
    assert raised.value.code == "web-search/unavailable"
    assert raised.value.message_key == "web-search-unavailable"
    assert any(
        entry["event"] == "web_search_key_refused" and entry["log_level"] == "error"
        for entry in logs
    )


async def test_a_rate_limit_is_a_busy_search_with_the_seconds_to_wait() -> None:
    with pytest.raises(WebSearchBusyError) as raised:
        await gateway(ExaCallError(status=429, retry_after=7.0)).search(call())

    assert raised.value.status == 429
    assert raised.value.message_key == "web-search-busy"
    assert raised.value.params == {"seconds": 7}
    assert isinstance(raised.value, WebSearchUnavailableError)


async def test_a_rate_limit_without_retry_after_says_a_minute() -> None:
    with pytest.raises(WebSearchBusyError) as raised:
        await gateway(ExaCallError(status=429)).search(call())

    assert raised.value.params == {"seconds": 60}


async def test_a_server_error_and_an_unusable_answer_are_unavailable() -> None:
    with pytest.raises(WebSearchUnavailableError, match="HTTP 500"):
        await gateway(ExaCallError(status=500, details="oops")).search(call())
    with pytest.raises(WebSearchUnavailableError, match="without results"):
        await gateway({"requestId": "x"}).search(call())


def real_search() -> tuple[ExaClient, ExaWebSearch]:
    """The real client and the adapter over it (respx answers for it)."""
    client = ExaClient(api_key=KEY, base_url="https://api.exa.ai", timeout_seconds=5)
    return client, ExaWebSearch(client, WebSearchSettings(), ExaSettings())


@respx.mock
async def test_a_429_from_the_real_client_says_when_to_retry() -> None:
    client, search = real_search()
    respx.post(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "9"}))

    with pytest.raises(WebSearchBusyError) as busy:
        await search.search(call())
    await client.aclose()

    assert busy.value.params == {"seconds": 9}


@respx.mock
async def test_a_slow_real_client_is_an_empty_reply_with_a_notice() -> None:
    client, search = real_search()
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))

    reply = await search.search(call())
    await client.aclose()

    assert reply.notice == "timeout"
    assert reply.hits == ()


@respx.mock
async def test_a_connection_failure_from_the_real_client_is_unavailable() -> None:
    client, search = real_search()
    respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(WebSearchUnavailableError, match="transport: ConnectError"):
        await search.search(call())
    await client.aclose()


@respx.mock
async def test_a_non_json_answer_from_the_real_client_is_unavailable() -> None:
    client, search = real_search()
    respx.post(URL).mock(return_value=httpx.Response(200, text="<html>"))

    with pytest.raises(WebSearchUnavailableError, match="not JSON"):
        await search.search(call())
    await client.aclose()


@respx.mock
async def test_the_key_never_reaches_the_logs_or_the_errors() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(401, json={"error": "Invalid API key"})
    )
    client = ExaClient(api_key=KEY, base_url="https://api.exa.ai", timeout_seconds=5)
    search = ExaWebSearch(client, WebSearchSettings(), ExaSettings(mode="real"))

    with capture_logs() as logs:
        with pytest.raises(WebSearchUnavailableError) as raised:
            await search.search(call())
    await client.aclose()

    seen = repr(logs) + repr(raised.value.support_details) + repr(raised.value.params)
    assert KEY not in seen


# - - - fake mode and wiring - - -


async def test_the_fake_answers_the_same_query_the_same_way_in_exas_shape() -> None:
    first = await ExaWebSearch(
        FakeExaClient(), WebSearchSettings(), ExaSettings()
    ).search(call())
    second = await ExaWebSearch(
        FakeExaClient(), WebSearchSettings(), ExaSettings()
    ).search(call())

    assert first.hits == second.hits
    assert {hit.site for hit in first.hits} == {
        "uz.wikipedia.org",
        "ru.wikipedia.org",
        "en.wikipedia.org",
    }
    assert all(hit.why.startswith("(fake)") for hit in first.hits)
    assert first.cost_micro == 0


async def test_the_fake_can_report_a_charge_for_tests() -> None:
    reply = await ExaWebSearch(
        FakeExaClient(cost_dollars=0.007), WebSearchSettings(), ExaSettings()
    ).search(call(explain=False))

    assert reply.cost_micro == 7000


def test_fake_mode_gets_the_fake_client_and_real_mode_needs_a_key() -> None:
    settings = Settings()
    fake = make_web_search_gateway(settings, None)
    assert isinstance(fake, ExaWebSearch)
    assert isinstance(fake.client, FakeExaClient)

    real = settings.model_copy(update={"exa": ExaSettings(mode="real")})
    with pytest.raises(ValueError, match="EXA__API_KEY is required"):
        make_web_search_gateway(real, FakeRedis())

    keyed = settings.model_copy(
        update={"exa": ExaSettings(mode="real", api_key=SecretStr(KEY))}
    )
    with pytest.raises(ValueError, match="Redis is required"):
        make_web_search_gateway(keyed, None)
    real_gateway = make_web_search_gateway(keyed, FakeRedis())
    assert isinstance(real_gateway, ExaWebSearch)
    assert isinstance(real_gateway.client, LimitedExa)
