"""NB-31, NB-32: the OpenRouter web search adapter against recorded-shape responses."""

import json
from pathlib import Path
from typing import Any

from app.modules.ai.infrastructure.openrouter import OpenRouterGateway
from app.modules.ai.infrastructure.openrouter_search import (
    OpenRouterWebSearch,
    build_search_payload,
    reason_after,
)
from app.settings import Settings
from app.settings_web_search import WebSearchSettings
from app.shared.ai_tasks import AiTask
from app.shared.contracts.web_search import SearchCall, WebSearchUnavailableError

import httpx
import pytest
import respx

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "openrouter"
URL = "https://openrouter.ai/api/v1/chat/completions"


def fixture(name: str) -> dict[str, Any]:
    """Load a recorded response."""
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text())
    return data


def make_call(*, explain: bool = True, task: AiTask = AiTask.DISCOVER) -> SearchCall:
    """A Discover call with the default profile of the task."""
    return SearchCall(
        query="how does photosynthesis work",
        language="en",
        max_results=5,
        explain=explain,
        profile=Settings().ai_profile(task),
        exclude_domains=("pornhub.com",),
    )


async def no_sleep(seconds: float) -> None:
    """Retries do not wait in tests."""


def search_adapter(config: WebSearchSettings | None = None) -> OpenRouterWebSearch:
    """An adapter over a gateway with a test key."""
    gateway = OpenRouterGateway(
        api_key="sk-test",
        base_url="https://openrouter.ai/api/v1",
        app_url="https://sp.ihsu.uz",
        app_title="IHSP",
        timeout_seconds=5,
        sleep=no_sleep,
    )
    return OpenRouterWebSearch(gateway, config or WebSearchSettings())


def sent(route: respx.Route) -> dict[str, Any]:
    """The JSON body of the request the adapter sent."""
    body: dict[str, Any] = json.loads(route.calls.last.request.content)
    return body


# - - - the request - - -


def test_the_plugin_surface_adds_the_web_plugin_with_the_blocklist() -> None:
    config = WebSearchSettings(engine="exa", mode="auto")

    payload = build_search_payload(make_call(), config)

    assert payload["plugins"] == [
        {
            "id": "web",
            "engine": "exa",
            "max_results": 5,
            "search_prompt": payload["plugins"][0]["search_prompt"],
            "mode": "auto",
            "exclude_domains": ["pornhub.com"],
        }
    ]
    assert "tools" not in payload
    assert payload["model"] == "google/gemini-3.5-flash-lite"
    assert payload["provider"] == {"data_collection": "deny"}


def test_the_server_tool_surface_limits_one_search_and_the_text_per_result() -> None:
    config = WebSearchSettings(surface="server_tool", engine="parallel")

    payload = build_search_payload(make_call(), config)

    assert "plugins" not in payload
    assert payload["tools"] == [
        {
            "type": "openrouter:web_search",
            "parameters": {
                "engine": "parallel",
                "max_results": 5,
                "max_uses": 1,
                "max_characters": 1200,
                "excluded_domains": ["pornhub.com"],
            },
        }
    ]
    assert payload["max_tool_calls"] == 2


def test_the_request_asks_for_the_students_language_and_age() -> None:
    call = SearchCall(
        query="fotosintez",
        language="uz",
        max_results=3,
        explain=False,
        profile=Settings().ai_profile(AiTask.WEB_SEARCH),
    )

    text = build_search_payload(call, WebSearchSettings())["messages"][1]["content"]

    assert "Request: fotosintez" in text
    assert "aged 14 to 18" in text
    assert "Uzbek" in text
    assert "at most 3 pages" in text
    assert "why it helps" not in text


# - - - the response - - -


@respx.mock
async def test_hits_come_from_the_annotations_with_the_reason_from_the_text() -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, json=fixture("web_search_plugin"))
    )

    reply = await search_adapter().search(make_call())

    assert sent(route)["plugins"][0]["id"] == "web"
    assert [hit.url for hit in reply.hits] == [
        "https://en.wikipedia.org/wiki/Photosynthesis",
        "https://www.khanacademy.org/science/biology/photosynthesis-in-plants",
    ]
    first = reply.hits[0]
    assert first.title == "Photosynthesis - Wikipedia"
    assert first.site == "en.wikipedia.org"
    assert first.why == "A full article on how plants turn light into sugar."
    assert first.snippet.startswith("Photosynthesis is a biological process. …")
    assert "[...]" not in first.snippet
    assert reply.usage["input"] == 4200


@respx.mock
async def test_duplicates_blocked_hosts_and_non_web_urls_are_dropped() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=fixture("web_search_plugin"))
    )

    reply = await search_adapter().search(make_call())

    urls = [hit.url for hit in reply.hits]
    assert not any("pornhub" in url for url in urls)  # blocked
    assert not any(url.startswith("ftp:") for url in urls)  # not a web page
    assert len(urls) == len({url.rstrip("/") for url in urls})  # one per page


@respx.mock
async def test_a_chat_search_does_not_ask_for_reasons() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=fixture("web_search_plugin"))
    )

    reply = await search_adapter().search(make_call(explain=False))

    assert all(hit.why == "" for hit in reply.hits)


@respx.mock
async def test_links_the_model_wrote_without_an_annotation_are_not_hits() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=fixture("web_search_no_annotations"))
    )

    reply = await search_adapter().search(make_call())

    assert reply.hits == ()


@respx.mock
async def test_the_result_count_is_capped() -> None:
    respx.post(URL).mock(
        return_value=httpx.Response(200, json=fixture("web_search_plugin"))
    )
    call = SearchCall(
        query="q",
        language="en",
        max_results=1,
        explain=True,
        profile=Settings().ai_profile(AiTask.DISCOVER),
    )

    reply = await search_adapter().search(call)

    assert len(reply.hits) == 1


@respx.mock
async def test_a_provider_failure_is_a_search_failure() -> None:
    respx.post(URL).mock(return_value=httpx.Response(503, json={"error": {}}))
    adapter = search_adapter()

    with pytest.raises(WebSearchUnavailableError):
        await adapter.search(make_call())


def test_the_reason_is_the_rest_of_the_line_after_the_link() -> None:
    text = "- [A](https://a.org/x) — Short and clear.\n- [B](https://b.org/y) - Other."

    assert reason_after(text, "https://a.org/x") == "Short and clear."
    assert reason_after(text, "https://b.org/y") == "Other."
    assert reason_after(text, "https://c.org/") == ""
