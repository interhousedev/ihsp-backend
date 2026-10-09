"""HTTP: the web toggle of the assistant chat and `GET /v1/ai/web-search` (NB-32/33)."""

from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.ai import ROUTERS as AI_ROUTERS
from app.interfaces.http.v1.web_search import ROUTERS as WEB_ROUTERS
from app.shared.actor import Actor
from app.shared.clock import local_today
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import text_reply

import pytest
from httpx import AsyncClient

STATUS_KEYS = {
    "enabled",
    "used",
    "limit",
    "remaining",
    "resets_at",
    "max_results",
    "deep_cost",
}
WEB_KEYS = {"n", "title", "url", "site", "snippet", "why", "cited"}


@pytest.fixture
def current() -> dict[str, Actor]:
    """The actor the next request runs as."""
    return {}


@pytest.fixture
async def api(
    make_harness: HarnessFactory, http_client: Any, current: dict[str, Actor]
) -> tuple[AiHarness, AsyncClient]:
    """The harness and a client of the AI and web search routes."""
    h = make_harness()
    current["actor"] = h.student
    client = await http_client(
        [*AI_ROUTERS, *WEB_ROUTERS],
        {get_actor: lambda: current["actor"]},
        ai=h.services,
    )
    return h, client


async def new_chat(client: AsyncClient) -> str:
    """Create a student chat and return its id."""
    response = await client.post("/v1/ai/chats", json={"assistant": "student"})
    return str(response.json()["id"])


async def test_the_status_says_how_many_searches_are_left(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """NB-33: "10 of 10 searches left today" before the first one."""
    _, client = api

    response = await client.get("/v1/ai/web-search")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == STATUS_KEYS
    assert body["enabled"] is True
    assert (body["used"], body["limit"], body["remaining"]) == (0, 10, 10)
    assert (body["max_results"], body["deep_cost"]) == (5, 3)
    assert body["resets_at"].endswith("Z")


async def test_a_message_with_web_search_returns_the_pages_and_updates_the_status(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    h, client = api
    chat_id = await new_chat(client)
    h.llm.push(text_reply("Plants make sugar [[W2]]."))

    response = await client.post(
        f"/v1/ai/chats/{chat_id}/messages",
        json={"text": "What is photosynthesis?", "web_search": True},
    )

    assert response.status_code == 200, response.text
    user, answer = response.json()["new_messages"]
    assert [set(item) for item in user["web"]] == [WEB_KEYS] * 3
    assert answer["text"] == "Plants make sugar ⟦w2⟧."
    assert [item["cited"] for item in answer["web"]] == [False, True, False]
    status = (await client.get("/v1/ai/web-search")).json()
    assert (status["used"], status["remaining"]) == (1, 9)
    opened = (await client.get(f"/v1/ai/chats/{chat_id}")).json()
    assert opened["messages"][1]["web"][1]["url"] == answer["web"][1]["url"]


async def test_the_flag_defaults_to_off_for_a_message(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    h, client = api
    chat_id = await new_chat(client)

    response = await client.post(
        f"/v1/ai/chats/{chat_id}/messages", json={"text": "hello"}
    )

    assert response.status_code == 200
    assert h.search.calls == []
    assert (await client.get("/v1/ai/web-search")).json()["used"] == 0


async def test_when_the_searches_are_used_up_the_answer_is_429_and_nothing_is_stored(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    """NB-33: problem+json `web-search/quota-exceeded` with the reset time."""
    h, client = api
    chat_id = await new_chat(client)
    await h.search_quota.add(h.student.user_id, local_today(h.clock), 10)

    response = await client.post(
        f"/v1/ai/chats/{chat_id}/messages", json={"text": "hello", "web_search": True}
    )

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "web-search/quota-exceeded"
    assert body["params"]["limit"] == 10 and "resets_at" in body["params"]
    assert (await client.get(f"/v1/ai/chats/{chat_id}")).json()["messages"] == []
    status = (await client.get("/v1/ai/web-search")).json()
    assert status["remaining"] == 0


async def test_with_the_feature_off_the_status_hides_the_toggle_and_a_message_is_404(
    make_harness: HarnessFactory, http_client: Any
) -> None:
    h = make_harness(features={"web_search": False})
    client = await http_client(
        [*AI_ROUTERS, *WEB_ROUTERS],
        {get_actor: lambda: h.student},
        ai=h.services,
    )
    chat_id = await new_chat(client)

    status = await client.get("/v1/ai/web-search")
    refused = await client.post(
        f"/v1/ai/chats/{chat_id}/messages", json={"text": "hi", "web_search": True}
    )

    assert status.json()["enabled"] is False
    assert refused.status_code == 404
    assert refused.json()["type"] == "web-search/disabled"


async def test_a_provider_failure_is_503_and_costs_nothing(
    api: tuple[AiHarness, AsyncClient],
) -> None:
    h, client = api
    chat_id = await new_chat(client)
    h.search.fail_next()

    response = await client.post(
        f"/v1/ai/chats/{chat_id}/messages", json={"text": "hi", "web_search": True}
    )

    assert response.status_code == 503
    assert response.json()["type"] == "web-search/unavailable"
    assert (await client.get("/v1/ai/web-search")).json()["used"] == 0
