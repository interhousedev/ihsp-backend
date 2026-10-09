"""HTTP: Discover and the web toggle of the notebook chat (NB-31 to NB-33)."""

import json
from typing import Any

from app.modules.notebooks.domain.entities import Notebook
from app.shared.clock import local_today
from app.shared.contracts.web_search import SearchReply
from tests.factories.notebooks import make_notebook, make_source
from tests.fakes.ai.web_search import WebRig, page
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.notebooks.http.test_chat_routes import (
    BIOLOGY,
    SSE,
    chat_url,
    event_names,
    parse_sse,
    problem_type,
    streamed_text,
)

import pytest
from httpx import AsyncClient

RESULT_KEYS = {"title", "url", "site", "snippet", "why", "already_added"}
QUOTA_KEYS = {
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
async def notebook(uow_factory: Any, student: Any) -> Notebook:
    """A notebook of the student with one ready source."""
    made = await make_notebook(uow_factory, student.user_id)
    await make_source(uow_factory, made, title="Biology", texts=BIOLOGY)
    return made


async def use_up(web: WebRig, student: Any) -> None:
    """Spend all of today's searches of the student."""
    day = local_today(web.service.clock)
    await web.store.add(student.user_id, day, web.service.limit_of(student))


def discover_url(notebook: Notebook) -> str:
    """The Discover route of the notebook."""
    return f"/v1/notebooks/{notebook.id}/discover"


# - - - POST /discover - - -


async def test_discover_returns_pages_and_the_quota(
    api: AsyncClient, notebook: Notebook
) -> None:
    """NB-31: exact keys; "9 of 10 searches left"."""
    response = await api.post(
        discover_url(notebook), json={"query": "photosynthesis", "mode": "fast"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"mode", "queries", "results", "quota"}
    assert body["mode"] == "fast" and body["queries"] == ["photosynthesis"]
    assert len(body["results"]) == 3
    assert set(body["results"][0]) == RESULT_KEYS
    assert body["results"][0]["why"] == "It explains the topic."
    assert body["results"][0]["already_added"] is False
    assert set(body["quota"]) == QUOTA_KEYS
    assert body["quota"]["enabled"] is True
    assert (body["quota"]["used"], body["quota"]["remaining"]) == (1, 9)


async def test_the_mode_defaults_to_fast_and_deep_costs_three(
    api: AsyncClient, notebook: Notebook, web: WebRig
) -> None:
    web.json.push({"queries": ["a", "b"]}, {"results": [{"index": 1, "why": "Best."}]})

    plain = await api.post(discover_url(notebook), json={"query": "topic"})
    deep = await api.post(
        discover_url(notebook), json={"query": "topic", "mode": "deep"}
    )

    assert plain.json()["mode"] == "fast"
    assert deep.json()["mode"] == "deep"
    assert deep.json()["queries"] == ["topic", "a", "b"]
    assert deep.json()["results"][0]["why"] == "Best."
    assert deep.json()["quota"]["used"] == 4


async def test_an_unknown_mode_is_a_validation_error(
    api: AsyncClient, notebook: Notebook
) -> None:
    response = await api.post(
        discover_url(notebook), json={"query": "topic", "mode": "research"}
    )

    assert response.status_code == 422


async def test_discover_answers_429_when_the_searches_are_used_up(
    api: AsyncClient, notebook: Notebook, web: WebRig, student: Any
) -> None:
    """NB-33: problem+json with the translated message and the reset time."""
    await use_up(web, student)

    response = await api.post(discover_url(notebook), json={"query": "topic"})

    assert problem_type(response, 429) == "web-search/quota-exceeded"
    body = response.json()
    assert "resets_at" in body["params"] and body["params"]["limit"] == 10


async def test_another_students_notebook_is_a_404(
    api: AsyncClient, uow_factory: Any, other_student: Any
) -> None:
    theirs = await make_notebook(uow_factory, other_student.user_id)

    response = await api.post(discover_url(theirs), json={"query": "topic"})

    assert problem_type(response, 404) == "notebooks/not-found"


async def test_a_one_letter_request_is_a_422(
    api: AsyncClient, notebook: Notebook
) -> None:
    response = await api.post(discover_url(notebook), json={"query": "a"})

    assert problem_type(response, 422) == "notebooks/invalid-options"


# - - - adding what was found - - -


async def test_found_pages_are_added_through_the_ordinary_sources_route(
    api: AsyncClient, notebook: Notebook, web: WebRig
) -> None:
    """NB-31: `kind: "url"` with the title; the second add is marked already added."""
    same = SearchReply(hits=tuple(page(n, why="w") for n in (1, 2, 3)), usage={})
    web.search.push(same, same)
    found = (
        await api.post(discover_url(notebook), json={"query": "photosynthesis"})
    ).json()["results"]
    items = [{"kind": "url", "url": r["url"], "title": r["title"]} for r in found[:2]]

    added = await api.post(
        f"/v1/notebooks/{notebook.id}/sources", json={"items": items}
    )

    assert added.status_code == 201, added.text
    assert [s["title"] for s in added.json()["items"]] == [
        r["title"] for r in found[:2]
    ]
    assert added.json()["rejected"] == []
    again = (
        await api.post(discover_url(notebook), json={"query": "photosynthesis"})
    ).json()["results"]
    assert [r["already_added"] for r in again] == [True, True, False]


async def test_a_blocked_page_is_rejected_with_a_hint(
    api: AsyncClient, notebook: Notebook
) -> None:
    response = await api.post(
        f"/v1/notebooks/{notebook.id}/sources",
        json={"items": [{"kind": "url", "url": "https://www.pornhub.com/x"}]},
    )

    rejected = response.json()["rejected"]
    assert rejected[0]["error"]["type"] == "notebooks/source-unsupported"
    assert rejected[0]["error"]["params"] == {"hint": "blocked"}


# - - - the toggle in the chat - - -


async def test_a_question_with_web_search_returns_the_pages_and_web_chips(
    api: AsyncClient, notebook: Notebook, scripted_llm: ScriptedLlm
) -> None:
    """NB-32: `web_search: true` in the body; `web` on both messages."""
    scripted_llm.queue_text("Plants make sugar [[W2]].")

    response = await api.post(
        chat_url(notebook, "/messages"), json={"text": "Why?", "web_search": True}
    )

    assert response.status_code == 200, response.text
    turn = response.json()
    assert turn["user_message"]["web"] == []
    answer = turn["assistant_message"]
    assert answer["text"] == "Plants make sugar ⟦w2⟧."
    assert [set(item) for item in answer["web"]] == [WEB_KEYS] * 3
    assert [item["cited"] for item in answer["web"]] == [False, True, False]
    assert answer["grounded"] is True


async def test_a_question_without_the_toggle_has_an_empty_web_list(
    api: AsyncClient, notebook: Notebook, web: WebRig
) -> None:
    response = await api.post(chat_url(notebook, "/messages"), json={"text": "Why?"})

    assert response.json()["assistant_message"]["web"] == []
    assert web.search.calls == []


async def test_a_stream_sends_a_web_event_before_the_text(
    api: AsyncClient, notebook: Notebook, scripted_llm: ScriptedLlm
) -> None:
    """NB-32: `message`, `web`, `delta`..., `done` with the cited flags."""
    scripted_llm.queue_stream(["Sugar [", "[W1]] and oxygen."])

    response = await api.post(
        chat_url(notebook, "/messages"),
        json={"text": "Why?", "web_search": True},
        headers=SSE,
    )

    assert response.status_code == 200, response.text
    events = parse_sse(response.text)
    assert event_names(events)[:2] == ["message", "web"]
    assert event_names(events)[-1] == "done"
    web_event = dict(events[1][1])
    assert [set(item) for item in web_event["results"]] == [WEB_KEYS] * 3
    assert streamed_text(events) == "Sugar ⟦w1⟧ and oxygen."
    done = events[-1][1]["assistant_message"]
    assert [item["cited"] for item in done["web"]] == [True, False, False]
    json.dumps(done)  # serializable


async def test_a_stream_answers_429_before_it_starts_when_the_searches_are_gone(
    api: AsyncClient, notebook: Notebook, web: WebRig, student: Any
) -> None:
    await use_up(web, student)

    response = await api.post(
        chat_url(notebook, "/messages"),
        json={"text": "Q", "web_search": True},
        headers=SSE,
    )

    assert problem_type(response, 429) == "web-search/quota-exceeded"
    assert (await api.get(chat_url(notebook))).json() == {"messages": []}
