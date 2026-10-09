"""HTTP: the notebook chat routes (§ 3.3, § 4.3): JSON turns, events, notes."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from app.modules.notebooks.domain.entities import (
    Citation,
    MessageContent,
    Notebook,
    NotebookMessage,
    Source,
)
from app.modules.notebooks.domain.enums import MessageRole, SourceKind
from app.modules.notebooks.wiring import NotebooksServices
from app.shared.actor import Actor, Role
from app.shared.contracts.ai import AiProviderError
from app.shared.ids import new_id
from tests.factories.notebooks import make_message, make_notebook, make_source
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient, Response

BIOLOGY = (
    "Photosynthesis turns light into chemical energy in plants.",
    "It happens in the chloroplasts, which contain chlorophyll.",
)
ANSWER = 'Light becomes energy [[S1:P1]].\n<followups>["Where?","Why?"]</followups>'
ANSWER_TEXT = "Light becomes energy ⟦1⟧."
STREAMED: list[str | Exception] = [
    "Light becomes ",
    "energy [[S1",
    ":P1]].\n",
    '<followups>["Where?"]</followups>',
]
SSE = {"Accept": "text/event-stream"}
JSON_AND_SSE = [pytest.param({}, id="json"), pytest.param(SSE, id="stream")]

MESSAGE_KEYS = {
    "id",
    "seq",
    "role",
    "text",
    "citations",
    "followups",
    "source_ids",
    "web",
    "retrieval",
    "grounded",
    "feedback",
    "stopped",
    "created_at",
}
CITATION_KEYS = {
    "n",
    "passage_id",
    "source_id",
    "source_title",
    "source_kind",
    "page",
    "snippet",
}
SOURCE_ITEM_KEYS = {
    "id",
    "notebook_id",
    "kind",
    "title",
    "status",
    "failure",
    "selected",
    "position",
    "word_count",
    "passage_count",
    "origin",
    "ref",
    "stale",
    "has_guide",
    "synced_at",
    "created_at",
}
USAGE_KEYS = {"budget", "quotas", "generating", "generating_limit"}
QUOTA_NAMES = {"artifacts", "audio_overview", "slides", "infographic"}


# - - - fixtures and helpers - - -


@pytest.fixture
async def notebook(uow_factory: Any, student: Actor) -> Notebook:
    """A notebook of the student."""
    return await make_notebook(uow_factory, student.user_id)


@pytest.fixture
async def source(uow_factory: Any, notebook: Notebook) -> Source:
    """A ready source of the notebook with two passages."""
    return await make_source(uow_factory, notebook, title="Biology", texts=BIOLOGY)


def chat_url(notebook: Notebook, tail: str = "") -> str:
    """The URL of a chat route of the notebook."""
    return f"/v1/notebooks/{notebook.id}/chat{tail}"


def problem_type(response: Response, status: int) -> str:
    """Check a problem+json answer and return its `type`."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    return str(response.json()["type"])


def parse_sse(raw: str) -> list[tuple[str, Any]]:
    """Split a raw body into (event, data) pairs and check the framing."""
    assert raw.endswith("\n\n")
    events: list[tuple[str, Any]] = []
    for block in raw[:-2].split("\n\n"):
        lines = block.split("\n")
        assert len(lines) == 2, block
        assert lines[0].startswith("event: ") and lines[1].startswith("data: "), block
        events.append(
            (lines[0][len("event: ") :], json.loads(lines[1][len("data: ") :]))
        )
    return events


def event_names(events: list[tuple[str, Any]]) -> list[str]:
    """The event names in order."""
    return [name for name, _ in events]


def streamed_text(events: list[tuple[str, Any]]) -> str:
    """The text of all `delta` events."""
    return "".join(data["text"] for name, data in events if name == "delta")


async def passage_ids(uow_factory: Any, source: Source) -> list[UUID]:
    """Ids of the stored passages of a source, by `seq`."""
    async with uow_factory() as uow:
        passages = await uow.passages.list_for_source(source.id, after_seq=0, limit=50)
    return [passage.id for passage in passages]


async def answered(
    uow_factory: Any, notebook: Notebook, source: Source, **fields: Any
) -> tuple[NotebookMessage, NotebookMessage]:
    """A stored question and an answer that cites the source."""
    question = await make_message(uow_factory, notebook, text="Q?")
    citation = Citation(
        n=1,
        passage_id=new_id(),
        source_id=source.id,
        source_title=source.title,
        source_kind=SourceKind.TEXT,
        snippet=BIOLOGY[0],
    )
    content = MessageContent(
        text=ANSWER_TEXT,
        citations=[citation],
        followups=["Where?"],
        source_ids=[source.id],
        grounded=True,
    )
    answer = await make_message(
        uow_factory,
        notebook,
        role=MessageRole.ASSISTANT,
        content=content,
        **fields,
    )
    return question, answer


async def history(api: AsyncClient, notebook: Notebook) -> list[dict[str, Any]]:
    """The chat as the student reads it."""
    response = await api.get(chat_url(notebook))
    assert response.status_code == 200, response.text
    messages: list[dict[str, Any]] = response.json()["messages"]
    return messages


# - - - GET /chat - - -


async def test_the_chat_lists_the_thread_with_the_contract_fields(
    api: AsyncClient, uow_factory: Any, notebook: Notebook, source: Source
) -> None:
    """NB-6: `{messages}` ascending; a message has exactly the § 4.4 keys."""
    question, answer = await answered(uow_factory, notebook, source, feedback=1)

    response = await api.get(chat_url(notebook))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"messages"}
    first, second = body["messages"]
    assert set(first) == MESSAGE_KEYS == set(second)
    assert (first["id"], first["seq"], first["role"]) == (str(question.id), 1, "user")
    assert first["text"] == "Q?" and first["citations"] == []
    assert first["feedback"] is None and first["stopped"] is False
    assert (second["id"], second["seq"], second["role"]) == (
        str(answer.id),
        2,
        "assistant",
    )
    assert second["text"] == ANSWER_TEXT and second["followups"] == ["Where?"]
    assert second["source_ids"] == [str(source.id)] and second["grounded"] is True
    assert second["retrieval"] is False and second["feedback"] == "up"
    assert set(second["citations"][0]) == CITATION_KEYS
    assert second["citations"][0]["source_kind"] == "text"
    assert second["citations"][0]["page"] is None
    assert datetime.fromisoformat(second["created_at"])


async def test_a_thumb_down_and_a_stopped_answer_are_shown(
    api: AsyncClient, uow_factory: Any, notebook: Notebook, source: Source
) -> None:
    """NB-7: stored -1 reads `down`; `stopped` is passed through."""
    await answered(uow_factory, notebook, source, feedback=-1, stopped=True)

    messages = await history(api, notebook)

    assert messages[1]["feedback"] == "down" and messages[1]["stopped"] is True


async def test_an_empty_chat_is_an_empty_list(
    api: AsyncClient, notebook: Notebook
) -> None:
    """NB-6: no messages yet."""
    response = await api.get(chat_url(notebook))

    assert response.status_code == 200 and response.json() == {"messages": []}


async def test_only_the_last_200_messages_come_back_in_order(
    api: AsyncClient, uow_factory: Any, notebook: Notebook
) -> None:
    """NB-6: 205 stored messages: `seq` 6 to 205, ascending."""
    for _ in range(205):
        await make_message(uow_factory, notebook)

    messages = await history(api, notebook)

    assert [item["seq"] for item in messages] == list(range(6, 206))


# - - - POST /chat/messages as JSON - - -


async def test_asking_returns_a_turn_with_citations_and_usage(
    api: AsyncClient,
    notebook: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
    uow_factory: Any,
) -> None:
    """NB-6, NB-14: `NotebookTurn` with exact keys; the chat shows the same messages."""
    scripted_llm.queue_text(ANSWER)
    first_passage = (await passage_ids(uow_factory, source))[0]

    response = await api.post(chat_url(notebook, "/messages"), json={"text": "Why?"})

    assert response.status_code == 200
    turn = response.json()
    assert set(turn) == {"user_message", "assistant_message", "usage", "action"}
    user, answer = turn["user_message"], turn["assistant_message"]
    assert set(user) == MESSAGE_KEYS == set(answer)
    assert (user["role"], user["seq"], user["text"]) == ("user", 1, "Why?")
    assert (answer["role"], answer["seq"]) == ("assistant", 2)
    assert answer["text"] == ANSWER_TEXT and answer["followups"] == ["Where?", "Why?"]
    assert answer["grounded"] is True and answer["retrieval"] is False
    assert answer["source_ids"] == [str(source.id)]
    assert answer["feedback"] is None and answer["stopped"] is False
    (citation,) = answer["citations"]
    assert set(citation) == CITATION_KEYS
    assert citation["n"] == 1 and citation["passage_id"] == str(first_passage)
    assert citation["source_id"] == str(source.id)
    assert citation["source_title"] == "Biology" and citation["source_kind"] == "text"
    assert citation["page"] is None
    assert citation["snippet"].startswith("Photosynthesis turns light")
    assert turn["action"] is None
    assert set(turn["usage"]) == USAGE_KEYS
    assert set(turn["usage"]["budget"]) == {"session", "day"}
    assert set(turn["usage"]["quotas"]) == QUOTA_NAMES
    assert turn["usage"]["budget"]["day"]["used"] > 0
    assert await history(api, notebook) == [user, answer]


async def test_source_ids_choose_the_sources_to_ask(
    api: AsyncClient,
    uow_factory: Any,
    notebook: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-5, NB-6: `source_ids` override the selection."""
    other = await make_source(uow_factory, notebook, title="Cells", texts=("Cells.",))
    scripted_llm.queue_text("Cells [[S1:P1]].")

    response = await api.post(
        chat_url(notebook, "/messages"),
        json={"text": "Q?", "source_ids": [str(other.id)]},
    )

    answer = response.json()["assistant_message"]
    assert answer["source_ids"] == [str(other.id)]
    assert answer["citations"][0]["source_id"] == str(other.id)


async def test_without_source_ids_the_selected_sources_are_asked(
    api: AsyncClient, uow_factory: Any, notebook: Notebook, source: Source
) -> None:
    """NB-5: the persisted selection is the default."""
    await make_source(
        uow_factory, notebook, title="Off", texts=("Hidden.",), selected=False
    )

    response = await api.post(chat_url(notebook, "/messages"), json={"text": "Q?"})

    assert response.json()["assistant_message"]["source_ids"] == [str(source.id)]


async def test_an_anchor_of_passages_focuses_the_question(
    api: AsyncClient,
    uow_factory: Any,
    notebook: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-6: pinned passage ids reach the model as a focus note."""
    second = (await passage_ids(uow_factory, source))[1]

    response = await api.post(
        chat_url(notebook, "/messages"),
        json={"text": "Explain", "anchor": {"kind": "passages", "ids": [str(second)]}},
    )

    assert response.status_code == 200
    question = str(scripted_llm.text_requests[-1]["messages"][-1]["content"])
    assert "Focus on passages S1:P2" in question


async def test_an_anchor_of_text_is_given_to_the_model(
    api: AsyncClient, notebook: Notebook, source: Source, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: a selected text reaches the model as the topic the student clicked."""
    response = await api.post(
        chat_url(notebook, "/messages"),
        json={"text": "Explain", "anchor": {"kind": "text", "text": "chlorophyll"}},
    )

    assert response.status_code == 200
    question = str(scripted_llm.text_requests[-1]["messages"][-1]["content"])
    assert "The student clicked on this topic: chlorophyll" in question


@pytest.mark.parametrize(
    "anchor",
    [
        pytest.param({"kind": "video", "ids": []}, id="unknown-kind"),
        pytest.param({"kind": "text"}, id="text-missing"),
        pytest.param({"kind": "text", "text": "x" * 4001}, id="text-too-long"),
        pytest.param(
            {"kind": "passages", "ids": [str(uuid4()) for _ in range(21)]},
            id="too-many-passages",
        ),
        pytest.param({"kind": "passages", "ids": ["nope"]}, id="bad-id"),
    ],
)
async def test_a_malformed_anchor_is_a_validation_error(
    api: AsyncClient, notebook: Notebook, source: Source, anchor: dict[str, Any]
) -> None:
    """NB-6: 422 before anything runs."""
    response = await api.post(
        chat_url(notebook, "/messages"), json={"text": "Q?", "anchor": anchor}
    )

    assert problem_type(response, 422) == "common/request-validation"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"text": ""}, id="empty"),
        pytest.param({}, id="missing"),
        pytest.param({"text": "x" * 8001}, id="over-8000"),
        pytest.param({"text": "Q?", "source_ids": ["nope"]}, id="bad-source-id"),
        pytest.param({"text": "Q?", "source_ids": [str(uuid4())] * 201}, id="201-ids"),
    ],
)
async def test_an_invalid_body_is_a_validation_error(
    api: AsyncClient, notebook: Notebook, source: Source, body: dict[str, Any]
) -> None:
    """NB-6: the request schema refuses it (422) and the model is never called."""
    response = await api.post(chat_url(notebook, "/messages"), json=body)

    assert problem_type(response, 422) == "common/request-validation"


@pytest.mark.parametrize("text", ["   \n ", "x" * 4001])
@pytest.mark.parametrize("headers", JSON_AND_SSE)
async def test_a_blank_or_too_long_question_is_refused_by_the_use_case(
    api: AsyncClient,
    notebook: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
    headers: dict[str, str],
    text: str,
) -> None:
    """NB-6: after trimming, 1 to 4 000 characters (`notebooks/invalid-options`)."""
    response = await api.post(
        chat_url(notebook, "/messages"), json={"text": text}, headers=headers
    )

    assert problem_type(response, 422) == "notebooks/invalid-options"
    assert response.json()["params"]["reason"] == "text-length"
    assert scripted_llm.calls == 0 and await history(api, notebook) == []


# - - - refusals: the same problem with and without the stream header - - -


@pytest.mark.parametrize("path", ["/messages", "/regenerate"])
@pytest.mark.parametrize("headers", JSON_AND_SSE)
async def test_a_notebook_of_another_student_is_a_404(
    api: AsyncClient,
    current: dict[str, Actor],
    other_student: Actor,
    notebook: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
    headers: dict[str, str],
    path: str,
) -> None:
    """NB-6, NB-15: `notebooks/not-found`, a plain response, no model call."""
    current["actor"] = other_student

    response = await api.post(
        chat_url(notebook, path), json={"text": "Q?"}, headers=headers
    )

    assert problem_type(response, 404) == "notebooks/not-found"
    assert scripted_llm.calls == 0


@pytest.mark.parametrize("headers", JSON_AND_SSE)
async def test_no_selected_source_is_a_422(
    api: AsyncClient,
    uow_factory: Any,
    notebook: Notebook,
    scripted_llm: ScriptedLlm,
    headers: dict[str, str],
) -> None:
    """NB-5, NB-6: `notebooks/no-sources-selected`; nothing is stored."""
    await make_source(uow_factory, notebook, texts=("Hidden.",), selected=False)

    response = await api.post(
        chat_url(notebook, "/messages"), json={"text": "Q?"}, headers=headers
    )

    assert problem_type(response, 422) == "notebooks/no-sources-selected"
    assert scripted_llm.calls == 0 and await history(api, notebook) == []


@pytest.mark.parametrize("headers", JSON_AND_SSE)
async def test_an_exhausted_budget_is_a_429(
    api: AsyncClient,
    services: NotebooksServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
    headers: dict[str, str],
) -> None:
    """NB-14: `notebooks/limit-reached` with the scope and the reset time."""
    await services.ask_notebook.pipeline.core.budget.add(student.user_id, 10_000_000)

    response = await api.post(
        chat_url(notebook, "/messages"), json={"text": "Q?"}, headers=headers
    )

    assert problem_type(response, 429) == "notebooks/limit-reached"
    assert set(response.json()["params"]) >= {"scope", "resets_at"}
    assert scripted_llm.calls == 0 and await history(api, notebook) == []


async def test_the_eleventh_question_of_a_minute_is_a_429(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """NB-6: ten questions a minute; the next one is `common/rate-limited`."""
    for _ in range(10):
        ok = await api.post(chat_url(notebook, "/messages"), json={"text": "Q?"})
        assert ok.status_code == 200

    response = await api.post(
        chat_url(notebook, "/messages"), json={"text": "Q?"}, headers=SSE
    )

    assert problem_type(response, 429) == "common/rate-limited"


@pytest.mark.parametrize("path", ["/messages", "/regenerate"])
@pytest.mark.parametrize("headers", JSON_AND_SSE)
async def test_a_running_question_makes_the_next_one_a_409(
    api: AsyncClient,
    services: NotebooksServices,
    student: Actor,
    notebook: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
    uow_factory: Any,
    headers: dict[str, str],
    path: str,
) -> None:
    """NB-6: `notebooks/busy` while another question of the thread is running."""
    await answered(uow_factory, notebook, source)
    core = services.ask_notebook.pipeline.core

    async with core.turn_lock.hold(notebook.id, student.user_id):
        response = await api.post(
            chat_url(notebook, path), json={"text": "Q?"}, headers=headers
        )

    assert problem_type(response, 409) == "notebooks/busy"
    assert scripted_llm.calls == 0 and len(await history(api, notebook)) == 2


async def test_the_model_failing_in_json_mode_is_a_503(
    api: AsyncClient,
    notebook: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-6: `ai/provider-error`; nothing is stored."""
    scripted_llm.queue_error(AiProviderError())

    response = await api.post(chat_url(notebook, "/messages"), json={"text": "Q?"})

    assert problem_type(response, 503) == "ai/provider-error"
    assert await history(api, notebook) == []


# - - - POST /chat/messages as events - - -


async def test_the_stream_sends_message_deltas_a_citation_and_done(
    api: AsyncClient, notebook: Notebook, source: Source, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: event order and payload names, parsed from the raw body."""
    scripted_llm.queue_stream(STREAMED)

    response = await api.post(
        chat_url(notebook, "/messages"), json={"text": "Why?"}, headers=SSE
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    events = parse_sse(response.text)
    names = event_names(events)
    assert names[0] == "message" and names[-1] == "done"
    assert set(names[1:-1]) == {"delta", "citation"} and names.count("citation") == 1
    assert streamed_text(events) == ANSWER_TEXT
    chip = next(i for i, (_, data) in enumerate(events) if "⟦" in data.get("text", ""))
    assert names.index("citation") < chip
    stored = await history(api, notebook)
    assert events[0][1] == {"id": stored[0]["id"], "seq": 1}
    citation = next(data for name, data in events if name == "citation")
    assert set(citation) == CITATION_KEYS and citation == stored[1]["citations"][0]
    assert all(set(d) == {"text"} for n, d in events if n == "delta")


async def test_done_carries_the_stored_answer_the_usage_and_the_action(
    api: AsyncClient, notebook: Notebook, source: Source, scripted_llm: ScriptedLlm
) -> None:
    """NB-6, NB-14: `done` is `{assistant_message, usage, action}`, as the web reads."""
    scripted_llm.queue_stream(STREAMED)

    response = await api.post(
        chat_url(notebook, "/messages"), json={"text": "Why?"}, headers=SSE
    )

    done = parse_sse(response.text)[-1][1]
    assert set(done) == {"assistant_message", "usage", "action"}
    answer = done["assistant_message"]
    assert set(answer) == MESSAGE_KEYS
    stored = (await history(api, notebook))[1]
    assert datetime.fromisoformat(answer.pop("created_at")) == datetime.fromisoformat(
        stored.pop("created_at")
    )
    assert answer == stored
    assert answer["text"] == ANSWER_TEXT and answer["followups"] == ["Where?"]
    assert answer["grounded"] is True and answer["stopped"] is False
    assert set(done["usage"]) == USAGE_KEYS and done["action"] is None
    assert done["usage"]["budget"]["day"]["used"] > 0


async def test_a_partial_marker_never_reaches_the_client(
    api: AsyncClient, notebook: Notebook, source: Source, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: the model sends one character at a time; `[[` is never shown."""
    chunks: list[str | Exception] = list(
        'Fact [[S1:P1]] and more [[S1:P2]].\n<followups>["a"]</followups>'
    )
    scripted_llm.queue_stream(chunks)

    response = await api.post(
        chat_url(notebook, "/messages"), json={"text": "Q?"}, headers=SSE
    )

    events = parse_sse(response.text)
    deltas = [data["text"] for name, data in events if name == "delta"]
    assert deltas and all("[" not in d and "S1:P" not in d for d in deltas)
    assert "[[" not in response.text and "S1:P" not in response.text
    assert "".join(deltas) == "Fact ⟦1⟧ and more ⟦2⟧."
    assert [d["n"] for n, d in events if n == "citation"] == [1, 2]
    assert events[-1][1]["assistant_message"]["text"] == "Fact ⟦1⟧ and more ⟦2⟧."


async def test_a_model_failure_in_the_stream_is_an_error_event(
    api: AsyncClient, notebook: Notebook, source: Source, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: after the question is stored the failure is the last event, status 200."""
    scripted_llm.queue_stream(["Partial text. ", AiProviderError()])

    response = await api.post(
        chat_url(notebook, "/messages"), json={"text": "Q?"}, headers=SSE
    )

    assert response.status_code == 200
    events = parse_sse(response.text)
    assert event_names(events)[0] == "message" and event_names(events)[-1] == "error"
    error = events[-1][1]
    assert set(error) == {"type", "title", "message_key", "params"}
    assert error["type"] == "ai/provider-error" and error["params"] == {}
    assert [m["role"] for m in await history(api, notebook)] == ["user"]


@pytest.mark.parametrize(
    "accept",
    [
        pytest.param(None, id="no-header"),
        pytest.param("application/json", id="json"),
        pytest.param("*/*", id="any"),
    ],
)
async def test_without_the_event_header_the_answer_is_json(
    api: AsyncClient, notebook: Notebook, source: Source, accept: str | None
) -> None:
    """NB-6: only `Accept: text/event-stream` switches to events."""
    headers = {} if accept is None else {"Accept": accept}

    response = await api.post(
        chat_url(notebook, "/messages"), json={"text": "Q?"}, headers=headers
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert "assistant_message" in response.json()


async def test_the_event_header_among_others_switches_to_events(
    api: AsyncClient, notebook: Notebook, source: Source
) -> None:
    """NB-6: `text/event-stream, */*;q=0.1` is a request for events."""
    response = await api.post(
        chat_url(notebook, "/messages"),
        json={"text": "Q?"},
        headers={"Accept": "text/event-stream, */*;q=0.1"},
    )

    assert response.headers["content-type"].startswith("text/event-stream")
    assert event_names(parse_sse(response.text))[-1] == "done"


# - - - leaving mid-answer - - -


class Wire:
    """A raw ASGI connection: a test reads the body while it is sent, and hangs up.

    The HTTP client only returns when the response is complete and never drops the
    connection, so the dropped connection of a browser (the stop button) is played
    here against the real app.
    """

    def __init__(self, body: bytes) -> None:
        """Start with the request body ready and the client connected."""
        self.body = body
        self.sent: list[MutableMapping[str, Any]] = []
        self.hangup = asyncio.Event()
        self.asked = False

    async def receive(self) -> dict[str, Any]:
        """The request body first, then `http.disconnect` once the client hangs up."""
        if not self.asked:
            self.asked = True
            return {"type": "http.request", "body": self.body, "more_body": False}
        await self.hangup.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: MutableMapping[str, Any]) -> None:
        """Record what the server sends."""
        self.sent.append(message)

    def text(self) -> str:
        """The response body sent so far."""
        parts = [
            m.get("body", b"") for m in self.sent if m["type"] == "http.response.body"
        ]
        return b"".join(parts).decode()


def post_scope(path: str, body: bytes) -> dict[str, Any]:
    """The ASGI scope of an event-stream POST (spec 2.3, as uvicorn sends it)."""
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"test"),
            (b"accept", b"text/event-stream"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }


async def eventually(check: Callable[[], Awaitable[bool]], what: str) -> None:
    """Wait up to five seconds for a condition."""
    for _ in range(500):
        if await check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.mark.parametrize(
    ("said", "shown"),
    [
        pytest.param("Hello world. ", "event: delta", id="after-some-text"),
        pytest.param("", "event: message", id="before-any-text"),
    ],
)
async def test_a_dropped_connection_keeps_what_was_shown_and_frees_the_thread(
    api: AsyncClient,
    redis: FakeRedis,
    student: Actor,
    notebook: Notebook,
    source: Source,
    scripted_llm: ScriptedLlm,
    monkeypatch: pytest.MonkeyPatch,
    said: str,
    shown: str,
) -> None:
    """NB-6: the stop button stores the partial answer as `stopped`; asking goes on."""

    async def waiting(**_: Any) -> AsyncIterator[dict[str, Any]]:
        if said:
            yield {"delta": said}
        await asyncio.Event().wait()  # the model keeps thinking

    monkeypatch.setattr(scripted_llm, "stream", waiting)
    real_get = redis.get

    async def get_over_the_network(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0.01)  # releasing the lock talks to Redis
        return await real_get(*args, **kwargs)

    monkeypatch.setattr(redis, "get", get_over_the_network)
    lock = f"nb:turn:{notebook.id}:{student.user_id}"
    wire = Wire(json.dumps({"text": "Q?"}).encode())
    app = cast(ASGITransport, api._transport).app
    scope = post_scope(chat_url(notebook, "/messages"), wire.body)

    async def serve() -> None:
        await app(scope, wire.receive, wire.send)

    call = asyncio.create_task(serve())

    async def event_sent() -> bool:
        return shown in wire.text()

    await eventually(event_sent, shown)
    wire.hangup.set()
    await asyncio.wait_for(call, 5)

    async def lock_free() -> bool:
        return not await redis.exists(lock)

    await eventually(lock_free, "the thread lock to be released")
    messages = await history(api, notebook)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["stopped"] is True and messages[1]["text"] == said.strip()
    monkeypatch.undo()
    again = await api.post(chat_url(notebook, "/messages"), json={"text": "Again?"})
    assert again.status_code == 200 and again.json()["user_message"]["seq"] == 3


# - - - POST /chat/regenerate - - -


async def test_regenerating_replaces_only_the_last_answer(
    api: AsyncClient, notebook: Notebook, source: Source, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: the question stays; the last answer is new and keeps its `seq`."""
    for text in ("First [[S1:P1]].", "Second [[S1:P1]]."):
        scripted_llm.queue_text(text)
        await api.post(chat_url(notebook, "/messages"), json={"text": "Q?"})
    before = await history(api, notebook)
    scripted_llm.queue_text("Third try [[S1:P2]].")

    response = await api.post(chat_url(notebook, "/regenerate"))

    assert response.status_code == 200
    turn = response.json()
    assert set(turn) == {"user_message", "assistant_message", "usage", "action"}
    assert turn["user_message"] == before[2]
    assert turn["assistant_message"]["id"] != before[3]["id"]
    assert turn["assistant_message"]["seq"] == 4
    assert turn["assistant_message"]["text"] == "Third try ⟦1⟧."
    after = await history(api, notebook)
    assert len(after) == 4 and after[:3] == before[:3]
    assert after[3] == turn["assistant_message"]


async def test_regenerating_as_events_reuses_the_stored_question(
    api: AsyncClient, notebook: Notebook, source: Source, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: `message` names the existing question; `done` is the new answer."""
    await api.post(chat_url(notebook, "/messages"), json={"text": "Q?"})
    before = await history(api, notebook)
    scripted_llm.queue_stream(STREAMED)

    response = await api.post(chat_url(notebook, "/regenerate"), headers=SSE)

    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert events[0] == ("message", {"id": before[0]["id"], "seq": 1})
    assert event_names(events)[-1] == "done"
    answer = events[-1][1]["assistant_message"]
    assert answer["seq"] == 2 and answer["id"] != before[1]["id"]
    assert answer["text"] == ANSWER_TEXT
    assert [m["id"] for m in await history(api, notebook)] == [
        before[0]["id"],
        answer["id"],
    ]


@pytest.mark.parametrize("headers", JSON_AND_SSE)
async def test_there_is_nothing_to_regenerate_in_an_empty_chat(
    api: AsyncClient, notebook: Notebook, source: Source, headers: dict[str, str]
) -> None:
    """NB-6: 422 `notebooks/invalid-options` (`nothing-to-regenerate`), plain."""
    response = await api.post(chat_url(notebook, "/regenerate"), headers=headers)

    assert problem_type(response, 422) == "notebooks/invalid-options"
    assert response.json()["params"]["reason"] == "nothing-to-regenerate"


# - - - DELETE /chat - - -


async def test_deleting_the_chat_clears_the_thread(
    api: AsyncClient, uow_factory: Any, notebook: Notebook, source: Source
) -> None:
    """NB-6: 204 with no body; the thread is empty afterwards."""
    await answered(uow_factory, notebook, source)

    response = await api.delete(chat_url(notebook))

    assert response.status_code == 204 and response.content == b""
    assert await history(api, notebook) == []


async def test_deleting_the_chat_of_another_student_is_a_404_and_keeps_it(
    api: AsyncClient,
    current: dict[str, Actor],
    other_student: Actor,
    student: Actor,
    uow_factory: Any,
    notebook: Notebook,
    source: Source,
) -> None:
    """NB-15: not the caller's notebook; the owner's messages stay."""
    await answered(uow_factory, notebook, source)
    current["actor"] = other_student

    response = await api.delete(chat_url(notebook))

    assert problem_type(response, 404) == "notebooks/not-found"
    current["actor"] = student
    assert len(await history(api, notebook)) == 2


async def test_deleting_the_chat_while_a_question_runs_is_a_409(
    api: AsyncClient,
    services: NotebooksServices,
    student: Actor,
    notebook: Notebook,
) -> None:
    """NB-6: `notebooks/busy`."""
    core = services.ask_notebook.pipeline.core

    async with core.turn_lock.hold(notebook.id, student.user_id):
        response = await api.delete(chat_url(notebook))

    assert problem_type(response, 409) == "notebooks/busy"


# - - - POST /chat/messages/{mid}/feedback - - -


async def test_feedback_is_stored_and_a_new_rating_replaces_the_old(
    api: AsyncClient, uow_factory: Any, notebook: Notebook, source: Source
) -> None:
    """NB-7: 204 with no body; the chat shows `up`, then `down`."""
    _, answer = await answered(uow_factory, notebook, source)
    url = chat_url(notebook, f"/messages/{answer.id}/feedback")

    up = await api.post(url, json={"rating": "up", "comment": "Clear"})
    shown_up = (await history(api, notebook))[1]["feedback"]
    down = await api.post(url, json={"rating": "down"})
    shown_down = (await history(api, notebook))[1]["feedback"]

    assert up.status_code == 204 and up.content == b""
    assert down.status_code == 204
    assert (shown_up, shown_down) == ("up", "down")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"rating": "meh"}, id="bad-rating"),
        pytest.param({}, id="no-rating"),
        pytest.param({"rating": "up", "comment": "x" * 1001}, id="long-comment"),
    ],
)
async def test_a_bad_feedback_body_is_a_validation_error(
    api: AsyncClient,
    uow_factory: Any,
    notebook: Notebook,
    source: Source,
    body: dict[str, Any],
) -> None:
    """NB-7: 422 before anything is stored."""
    _, answer = await answered(uow_factory, notebook, source)

    response = await api.post(
        chat_url(notebook, f"/messages/{answer.id}/feedback"), json=body
    )

    assert problem_type(response, 422) == "common/request-validation"
    assert (await history(api, notebook))[1]["feedback"] is None


async def test_feedback_only_goes_to_an_own_assistant_message(
    api: AsyncClient, uow_factory: Any, notebook: Notebook, source: Source
) -> None:
    """NB-7, NB-15: a question or an unknown id is a 404."""
    question, _ = await answered(uow_factory, notebook, source)
    body = {"rating": "up"}

    on_question = await api.post(
        chat_url(notebook, f"/messages/{question.id}/feedback"), json=body
    )
    unknown = await api.post(
        chat_url(notebook, f"/messages/{uuid4()}/feedback"), json=body
    )

    assert problem_type(on_question, 404) == "notebooks/not-found"
    assert problem_type(unknown, 404) == "notebooks/not-found"


async def test_a_message_of_another_notebook_is_not_found(
    api: AsyncClient,
    uow_factory: Any,
    student: Actor,
    notebook: Notebook,
    source: Source,
) -> None:
    """NB-7, NB-15: the id must belong to the notebook in the path."""
    _, answer = await answered(uow_factory, notebook, source)
    elsewhere = await make_notebook(uow_factory, student.user_id)

    response = await api.post(
        chat_url(elsewhere, f"/messages/{answer.id}/feedback"), json={"rating": "up"}
    )

    assert problem_type(response, 404) == "notebooks/not-found"


# - - - POST /chat/messages/{mid}/save-note - - -


async def test_saving_an_answer_creates_a_pending_note_with_its_citations(
    api: AsyncClient,
    uow_factory: Any,
    notebook: Notebook,
    source: Source,
    kicker: FakeTaskKicker,
) -> None:
    """NB-8: 201 `SourceItem`; the note holds the text and a copy of the citations."""
    _, answer = await answered(uow_factory, notebook, source)

    response = await api.post(
        chat_url(notebook, f"/messages/{answer.id}/save-note"),
        json={"title": "Light notes"},
    )

    assert response.status_code == 201
    note = response.json()
    assert set(note) == SOURCE_ITEM_KEYS
    assert note["kind"] == "note" and note["title"] == "Light notes"
    assert note["status"] == "pending" and note["selected"] is True
    assert note["notebook_id"] == str(notebook.id) and note["position"] == 2
    assert note["stale"] is False and note["has_guide"] is False
    async with uow_factory() as uow:
        stored = await uow.sources.get(UUID(note["id"]))
    assert stored is not None and stored.body_md == ANSWER_TEXT
    assert stored.citations == answer.content.citations
    assert ("notebooks.process_source", {"source_id": note["id"]}) in kicker.calls


@pytest.mark.parametrize("kwargs", [{}, {"json": {}}, {"json": {"title": None}}])
async def test_the_note_title_defaults_to_the_first_words_of_the_answer(
    api: AsyncClient,
    uow_factory: Any,
    notebook: Notebook,
    source: Source,
    kwargs: dict[str, Any],
) -> None:
    """NB-8: no body, an empty body or no title: the title comes from the text."""
    _, answer = await answered(uow_factory, notebook, source)

    response = await api.post(
        chat_url(notebook, f"/messages/{answer.id}/save-note"), **kwargs
    )

    assert response.status_code == 201
    assert response.json()["title"] == "Light becomes energy."


async def test_a_question_cannot_be_saved_as_a_note(
    api: AsyncClient, uow_factory: Any, notebook: Notebook, source: Source
) -> None:
    """NB-8, NB-15: only assistant messages; a question is a 404."""
    question, _ = await answered(uow_factory, notebook, source)

    response = await api.post(chat_url(notebook, f"/messages/{question.id}/save-note"))

    assert problem_type(response, 404) == "notebooks/not-found"


async def test_an_empty_answer_cannot_be_saved_as_a_note(
    api: AsyncClient, uow_factory: Any, notebook: Notebook, source: Source
) -> None:
    """NB-8: a stopped answer with no text is a 422 (`empty-answer`)."""
    await make_message(uow_factory, notebook)
    empty = await make_message(
        uow_factory, notebook, role=MessageRole.ASSISTANT, text="", stopped=True
    )

    response = await api.post(chat_url(notebook, f"/messages/{empty.id}/save-note"))

    assert problem_type(response, 422) == "notebooks/invalid-options"
    assert response.json()["params"]["reason"] == "empty-answer"


# - - - the contract in OpenAPI - - -


async def test_openapi_documents_both_answers_of_the_ask_routes(
    api: AsyncClient,
) -> None:
    """NB-6: JSON `NotebookTurn` or `text/event-stream` on both ask routes."""
    response = await api.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    for tail in ("/chat/messages", "/chat/regenerate"):
        (post,) = [v for k, v in paths.items() if k.endswith(tail)]
        content = post["post"]["responses"]["200"]["content"]
        assert set(content) == {"application/json", "text/event-stream"}


# - - - who may call - - -


def every_route(notebook_id: UUID, message_id: UUID) -> list[tuple[str, str, Any]]:
    """(method, path, JSON body) of the six chat routes."""
    base = f"/v1/notebooks/{notebook_id}/chat"
    message = f"{base}/messages/{message_id}"
    return [
        ("GET", base, None),
        ("POST", f"{base}/messages", {"text": "Q?"}),
        ("POST", f"{base}/regenerate", None),
        ("DELETE", base, None),
        ("POST", f"{message}/feedback", {"rating": "up"}),
        ("POST", f"{message}/save-note", {}),
    ]


async def test_a_teacher_gets_404_on_every_chat_route_of_a_student_notebook(
    api: AsyncClient,
    current: dict[str, Actor],
    make_actor: Callable[..., Actor],
    notebook: Notebook,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-15, LMS-AI 3.1: a student's notebook is theirs alone; a teacher gets the
    404 of a missing notebook (the routes are open to course staff for workspaces)."""
    current["actor"] = make_actor(Role.TEACHER)

    for method, path, body in every_route(notebook.id, uuid4()):
        response = await api.request(method, path, json=body)

        assert response.status_code == 404, (method, path)
        assert response.headers["content-type"].startswith("application/problem+json")
    assert scripted_llm.calls == 0


async def test_another_student_gets_404_on_every_chat_route(
    api: AsyncClient,
    current: dict[str, Actor],
    other_student: Actor,
    uow_factory: Any,
    notebook: Notebook,
    source: Source,
) -> None:
    """NB-15: a notebook of another student is not found, with real message ids too."""
    _, answer = await answered(uow_factory, notebook, source)
    current["actor"] = other_student

    for method, path, body in every_route(notebook.id, answer.id):
        response = await api.request(method, path, json=body)

        assert problem_type(response, 404) == "notebooks/not-found", (method, path)
