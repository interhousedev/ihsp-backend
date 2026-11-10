"""Parallel as the primary web search with Exa as the fallback and the deep partner."""

import json
from dataclasses import replace
from typing import Any

from app.modules.ai.infrastructure.exa import ExaCallError
from app.modules.ai.infrastructure.exa_rate_limit import ExaRateLimiter, LimitedExa
from app.modules.ai.infrastructure.exa_search import ExaWebSearch
from app.modules.ai.infrastructure.fake_parallel import FakeParallelClient
from app.modules.ai.infrastructure.gateway_factory import make_web_search_gateway
from app.modules.ai.infrastructure.parallel import ParallelClient
from app.modules.ai.infrastructure.parallel_search import (
    ParallelFirstWebSearch,
    ParallelWebSearch,
    parallel_body,
)
from app.settings import ExaSettings, ParallelSettings, Settings
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

KEY = "parallel-key-for-tests-only"
QUERY = "why is the sky blue"


class Stub:
    """Answers with the given object or raises it; records the bodies."""

    def __init__(self, answer: dict[str, Any] | ExaCallError) -> None:
        """Keep the answer."""
        self.answer = answer
        self.bodies: list[dict[str, Any]] = []

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Record the body, answer or raise."""
        self.bodies.append(body)
        if isinstance(self.answer, ExaCallError):
            raise self.answer
        return self.answer


def call(*, deep: bool = False, exclude: tuple[str, ...] = ()) -> SearchCall:
    """A search call the way the service makes it."""
    return SearchCall(
        query=QUERY,
        language="ru",
        max_results=5,
        explain=True,
        profile=Settings().ai_profile(AiTask.DISCOVER),
        exclude_domains=exclude,
        deep=deep,
    )


def p_page(n: int) -> dict[str, Any]:
    """One result of a Parallel answer."""
    return {
        "url": f"https://school{n}.example.org/sky",
        "title": f"Page {n}",
        "publish_date": "2025-03-01",
        "excerpts": [f"Excerpt {n}."],
    }


def e_page(n: int) -> dict[str, Any]:
    """One result of an Exa answer."""
    return {
        "url": f"https://school{n}.example.org/sky",
        "title": f"Exa {n}",
        "text": f"Text {n}.",
        "highlights": [f"Highlight {n}."],
    }


def parallel(answer: dict[str, Any] | ExaCallError) -> ParallelWebSearch:
    """The Parallel adapter over a stub."""
    return ParallelWebSearch(Stub(answer), WebSearchSettings(), ParallelSettings())


def exa(answer: dict[str, Any] | ExaCallError) -> ExaWebSearch:
    """The Exa adapter over a stub."""
    return ExaWebSearch(Stub(answer), WebSearchSettings(), ExaSettings())


def both(p: ParallelWebSearch, e: ExaWebSearch) -> ParallelFirstWebSearch:
    """The composite."""
    return ParallelFirstWebSearch(p, e)


def test_the_body_keeps_max_results_inside_advanced_settings() -> None:
    excluded = ("bad.example", "bad.example")
    body = parallel_body(call(exclude=excluded), ParallelSettings())

    assert body["search_queries"] == [QUERY]
    assert body["mode"] == "fast"
    assert QUERY in body["objective"]
    assert "max_results" not in body
    assert body["advanced_settings"] == {
        "max_results": 5,
        "source_policy": {"exclude_domains": ["bad.example"]},
    }


@respx.mock
async def test_the_real_client_posts_with_the_key_header_only() -> None:
    route = respx.post("https://api.parallel.ai/v1/search").mock(
        return_value=httpx.Response(200, json={"results": [p_page(1)]})
    )
    client = ParallelClient(
        api_key=KEY, base_url="https://api.parallel.ai", timeout_seconds=5
    )
    search = ParallelWebSearch(client, WebSearchSettings(), ParallelSettings())

    reply = await search.search(call())

    request = route.calls.last.request
    assert request.headers["x-api-key"] == KEY
    assert KEY not in request.content.decode()
    assert json.loads(request.content)["search_queries"] == [QUERY]
    assert [h.title for h in reply.hits] == ["Page 1"]
    assert reply.hits[0].why == "Excerpt 1."
    assert reply.provider == "parallel"


async def test_parallel_answers_and_exa_is_not_asked() -> None:
    e = exa({"results": [e_page(9)]})
    reply = await both(parallel({"results": [p_page(1)]}), e).search(call())

    assert reply.provider == "parallel"
    assert e.client.bodies == []  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "failure",
    [
        ExaCallError(status=500, details="boom"),
        ExaCallError(status=429, retry_after=3),
        ExaCallError(status=401),
        ExaCallError(timeout=True),
    ],
)
async def test_an_error_or_timeout_of_parallel_falls_back_to_exa(
    failure: ExaCallError,
) -> None:
    reply = await both(parallel(failure), exa({"results": [e_page(2)]})).search(call())

    assert reply.provider == "exa"
    assert [h.title for h in reply.hits] == ["Exa 2"]


async def test_an_empty_answer_of_parallel_falls_back_to_exa() -> None:
    gateway = both(parallel({"results": []}), exa({"results": [e_page(2)]}))

    reply = await gateway.search(call())

    assert reply.provider == "exa"
    assert len(reply.hits) == 1


async def test_exa_failing_after_an_empty_parallel_gives_the_empty_answer() -> None:
    gateway = both(parallel({"results": []}), exa(ExaCallError(status=500)))

    reply = await gateway.search(call())

    assert reply.hits == ()
    assert reply.provider == "parallel"


async def test_both_failing_raises_the_exa_error() -> None:
    failing = both(parallel(ExaCallError(status=500)), exa(ExaCallError(status=429)))

    with pytest.raises(WebSearchBusyError):
        await failing.search(call())


async def test_a_deep_search_merges_both_and_dedupes_by_url() -> None:
    gateway = both(
        parallel({"results": [p_page(1), p_page(2)]}),
        exa({"results": [e_page(2), e_page(3)]}),
    )

    reply = await gateway.search(call(deep=True))

    assert [h.site for h in reply.hits] == [
        "school1.example.org",
        "school2.example.org",
        "school3.example.org",
    ]
    assert reply.hits[1].title == "Page 2"  # Parallel first
    assert reply.provider == "parallel+exa"


async def test_a_deep_search_survives_one_failing_provider() -> None:
    gateway = both(parallel(ExaCallError(status=500)), exa({"results": [e_page(3)]}))

    reply = await gateway.search(call(deep=True))

    assert reply.provider == "exa"
    assert len(reply.hits) == 1


async def test_a_deep_search_fails_when_both_fail() -> None:
    gateway = both(parallel(ExaCallError(status=500)), exa(ExaCallError(status=500)))

    with pytest.raises(WebSearchUnavailableError):
        await gateway.search(call(deep=True))


async def test_the_fake_client_answers_in_parallels_shape() -> None:
    search = ParallelWebSearch(
        FakeParallelClient(), WebSearchSettings(), ParallelSettings()
    )

    reply = await search.search(replace(call(), max_results=2))

    assert len(reply.hits) == 2
    with pytest.raises(ExaCallError):
        await FakeParallelClient().search({"objective": "x"})


async def test_the_parallel_limiter_has_its_own_keys() -> None:
    redis = FakeRedis()
    limited = LimitedExa(
        Stub({"results": []}),
        ExaRateLimiter(redis, prefix="ai:parallel"),
        ParallelSettings(),
    )

    await limited.search({"search_queries": ["q"]})

    assert not await redis.exists("ai:exa:bucket")


def test_the_factory_builds_parallel_only_when_it_is_enabled() -> None:
    settings = Settings()
    keyless = settings.model_copy(update={"parallel": ParallelSettings(mode="live")})
    assert isinstance(make_web_search_gateway(keyless, None), ExaWebSearch)

    keyed = settings.model_copy(
        update={"parallel": ParallelSettings(mode="live", api_key=SecretStr(KEY))}
    )
    with pytest.raises(ValueError, match="Redis is required"):
        make_web_search_gateway(keyed, None)
    gateway = make_web_search_gateway(keyed, FakeRedis())
    assert isinstance(gateway, ParallelFirstWebSearch)
    assert isinstance(gateway.parallel, ParallelWebSearch)
    assert isinstance(gateway.parallel.client, LimitedExa)
