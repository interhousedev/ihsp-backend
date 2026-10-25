"""NB-6, NB-14: the answer as server-sent events and the stop button (§ 3.3.6)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.modules.notebooks.application.views import StreamEvent
from app.modules.notebooks.domain.enums import MessageRole
from app.modules.notebooks.domain.errors import (
    BusyError,
    InvalidOptionsError,
    LimitReachedError,
    NotebookNotFoundError,
)
from app.modules.notebooks.wiring_chat import ChatServices, build_chat
from app.modules.notebooks.wiring_core import NotebooksCore
from app.shared.actor import Actor
from app.shared.contracts.ai import AiProviderError
from tests.factories.notebooks import make_notebook
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.notebooks.unit.chat.support import (
    ANSWER_TEXT,
    CoreFactory,
    collect,
    names,
    notebook_with_source,
    passages_of,
    streamed_text,
    thread,
)

import pytest

STREAMED: list[str | Exception] = [
    "Light becomes ",
    "energy [[S1",
    ":P1]].\n",
    '<followups>["Where?"]</followups>',
]


class GatedLlm(ScriptedLlm):
    """Streams one chunk, then waits for the gate: a client that leaves mid-answer."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()

    async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        self.calls += 1
        self.stream_requests.append(kwargs)
        yield {"delta": "Hello world. "}
        await self.gate.wait()
        yield {"delta": "Never seen."}


class QuietLlm(ScriptedLlm):
    """Streams an answer and never reports usage."""

    async def stream(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        self.calls += 1
        yield {"delta": "Fact [[S1:P1]]."}


# - - - the happy path - - -


async def test_events_come_as_message_then_text_and_citations_then_done(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: `message`, `delta`/`citation` events, `done`; the citation comes first."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(STREAMED)

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Q?"))

    kinds = names(events)
    assert kinds[0] == "message" and kinds[-1] == "done"
    assert set(kinds[1:-1]) == {"delta", "citation"}
    assert kinds.count("citation") == 1
    assert streamed_text(events) == ANSWER_TEXT
    chip = next(i for i, e in enumerate(events) if "⟦" in e.data.get("text", ""))
    assert kinds.index("citation") < chip


async def test_the_message_event_names_the_stored_question(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: `message` carries the id and seq of the user message."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(STREAMED)

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Q?"))

    stored = await thread(core, student, notebook)
    assert events[0] == StreamEvent("message", {"id": str(stored[0].id), "seq": 1})
    assert stored[0].content.text == "Q?"


async def test_the_citation_event_is_the_stored_snapshot(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: `citation` has the fields of a stored citation."""
    notebook, source = await notebook_with_source(core, student)
    first = (await passages_of(core, source))[0]
    scripted_llm.queue_stream(STREAMED)

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Q?"))

    data = next(e for e in events if e.name == "citation").data
    assert set(data) == {
        "n",
        "passage_id",
        "source_id",
        "source_title",
        "source_kind",
        "page",
        "snippet",
    }
    assert data["n"] == 1 and data["passage_id"] == str(first.id)
    assert data["source_id"] == str(source.id) and data["source_title"] == "Biology"
    assert data["source_kind"] == "text" and data["page"] is None
    assert data["snippet"].startswith("Photosynthesis turns light")


async def test_done_carries_the_stored_answer_usage_and_action(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6, NB-14: `done` is the assistant message, the fresh usage and the action."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(STREAMED)

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Q?"))

    stored = await thread(core, student, notebook)
    done = events[-1].data
    message = done["message"]
    assert message["id"] == str(stored[1].id) and message["seq"] == 2
    assert message["role"] == "assistant" and message["text"] == ANSWER_TEXT
    assert message["followups"] == ["Where?"]
    assert message["source_ids"] == [str(stored[1].content.source_ids[0])]
    assert message["grounded"] is True and message["retrieval"] is False
    assert message["stopped"] is False and message["feedback"] is None
    assert [c["n"] for c in message["citations"]] == [1]
    assert done["usage"]["budget"]["day"]["used"] == stored[1].weighted
    assert done["usage"]["generating"] == 0
    assert done["action"] is None
    assert stored[1].content.text == streamed_text(events)
    assert stored[1].stopped is False


async def test_a_partial_marker_never_reaches_the_client(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: the answer arrives character by character; `[[` never shows up."""
    notebook, _ = await notebook_with_source(core, student)
    raw = 'Fact [[S1:P1]] and more [[S1:P2]].\n<followups>["a"]</followups>'
    chunks: list[str | Exception] = list(raw)
    scripted_llm.queue_stream(chunks)

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Q?"))

    deltas = [e.data["text"] for e in events if e.name == "delta"]
    assert deltas and all("[" not in piece and "S1:P" not in piece for piece in deltas)
    assert "".join(deltas) == "Fact ⟦1⟧ and more ⟦2⟧."
    assert [e.data["n"] for e in events if e.name == "citation"] == [1, 2]
    assert events[-1].data["message"]["text"] == "Fact ⟦1⟧ and more ⟦2⟧."


async def test_an_unfinished_marker_at_the_end_is_dropped(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: a cut-off `[[S1:P` is neither shown nor stored."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(["Fact [[S1:P1]] and ", "[[S1:P"])

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Q?"))

    assert "[" not in streamed_text(events)
    assert events[-1].data["message"]["text"] == "Fact ⟦1⟧ and"


async def test_without_provider_usage_the_estimate_is_charged(
    core: NotebooksCore, make_core: CoreFactory, student: Actor
) -> None:
    """NB-14: a stream that sends no usage is still counted in the budget."""
    quiet = build_chat(make_core(gateway=QuietLlm()))
    notebook, _ = await notebook_with_source(core, student)

    events = await collect(quiet.ask_notebook.stream(student, notebook.id, "Q?"))

    stored = await thread(core, student, notebook)
    assert events[-1].name == "done"
    assert stored[1].tokens_in and stored[1].tokens_out and stored[1].weighted
    assert (await core.budget.usage(student.user_id)).day.used == stored[1].weighted


# - - - failures - - -


async def test_a_provider_error_in_the_stream_becomes_an_error_event(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: problem fields in the event; the question stays, no answer, no charge."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(["Partial text. ", AiProviderError()])

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Q?"))

    assert names(events)[0] == "message" and names(events)[-1] == "error"
    assert events[-1].data == {
        "type": "ai/provider-error",
        "title": core.deps.i18n.t("en", "ai-provider-error"),
        "message_key": "ai-provider-error",
        "params": {},
    }
    stored = await thread(core, student, notebook)
    assert [m.role for m in stored] == [MessageRole.USER]
    assert (await core.budget.usage(student.user_id)).day.used == 0
    follow_up = await chat.ask_notebook.execute(student, notebook.id, "Again?")
    assert follow_up.assistant_message.seq == 3


async def test_an_unexpected_failure_is_reported_as_internal(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: a crash never leaks its message into the stream."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(["Partial. ", RuntimeError("secret detail")])

    events = await collect(chat.ask_notebook.stream(student, notebook.id, "Q?"))

    assert events[-1] == StreamEvent(
        "error",
        {
            "type": "common/internal",
            "title": "Internal Server Error",
            "message_key": "error-internal",
            "params": {},
        },
    )


async def test_errors_before_the_question_is_stored_are_raised(
    core: NotebooksCore,
    chat: ChatServices,
    student: Actor,
    other_student: Actor,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-6, NB-15: the caller gets a plain 404 (nothing was stored, nothing sent)."""
    notebook, _ = await notebook_with_source(core, student)

    with pytest.raises(NotebookNotFoundError):
        await anext(chat.ask_notebook.stream(other_student, notebook.id, "Q?"))

    assert scripted_llm.calls == 0
    assert await thread(core, student, notebook) == []


async def test_an_invalid_question_is_raised_by_the_stream(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-6: an empty question is a 422, not an event."""
    notebook, _ = await notebook_with_source(core, student)

    with pytest.raises(InvalidOptionsError):
        await anext(chat.ask_notebook.stream(student, notebook.id, "   "))


async def test_a_stream_without_sources_still_answers(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """T6.3: no selected source is not an error; the answer is stored ungrounded."""
    notebook = await make_notebook(core.uow_factory, student.user_id)
    scripted_llm.queue_text("A general answer.\n<followups>[]</followups>")

    events = [e async for e in chat.ask_notebook.stream(student, notebook.id, "Q?")]

    assert events
    stored = await thread(core, student, notebook)
    assert [m.role for m in stored] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert stored[1].content.grounded is False


async def test_busy_is_raised_by_the_stream(
    core: NotebooksCore, chat: ChatServices, student: Actor
) -> None:
    """NB-6: a second parallel question is refused with 409."""
    notebook, _ = await notebook_with_source(core, student)

    async with core.turn_lock.hold(notebook.id, student.user_id):
        with pytest.raises(BusyError):
            await anext(chat.ask_notebook.stream(student, notebook.id, "Q?"))

    assert await thread(core, student, notebook) == []


async def test_an_exhausted_budget_is_raised_before_the_question_is_stored(
    core: NotebooksCore,
    make_core: CoreFactory,
    student: Actor,
    scripted_llm: ScriptedLlm,
) -> None:
    """NB-14: 429 `limit-reached`; no message, no model call."""
    tight = build_chat(make_core(limits={"nb_daily_tokens_student": 100}))
    notebook, _ = await notebook_with_source(core, student)

    with pytest.raises(LimitReachedError):
        await anext(tight.ask_notebook.stream(student, notebook.id, "Q?"))

    assert scripted_llm.calls == 0
    assert await thread(core, student, notebook) == []


# - - - the stop button - - -


async def test_stopping_stores_the_partial_answer_with_its_citations(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: the client leaves; what it saw is stored with `stopped` and charged."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(["First part [[S1:P1]] ", "second part ", "third part."])
    events = chat.ask_notebook.stream(student, notebook.id, "Q?")

    async for event in events:
        if "⟦" in event.data.get("text", ""):
            break
    await events.aclose()

    stored = await thread(core, student, notebook)
    assert [m.role for m in stored] == [MessageRole.USER, MessageRole.ASSISTANT]
    partial = stored[1]
    assert partial.stopped is True and partial.seq == 2
    assert partial.content.text == "First part ⟦1⟧"
    assert [c.n for c in partial.content.citations] == [1]
    assert partial.content.grounded is True and partial.content.followups == []
    assert partial.tokens_in and partial.weighted
    assert (await core.budget.usage(student.user_id)).day.used == partial.weighted


async def test_stopping_before_any_text_keeps_the_question_and_an_empty_answer(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: leaving right after `message` still leaves a thread that can go on."""
    notebook, _ = await notebook_with_source(core, student)
    events = chat.ask_notebook.stream(student, notebook.id, "Q?")

    first = await anext(events)
    assert first.name == "message"
    assert [m.role for m in await thread(core, student, notebook)] == [MessageRole.USER]
    await events.aclose()

    stored = await thread(core, student, notebook)
    assert [m.role for m in stored] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert stored[1].stopped is True and stored[1].content.text == ""
    assert stored[1].content.grounded is False


async def test_the_lock_is_free_after_stopping(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: the next question works right after a stop."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(["Some text. ", "more."])
    events = chat.ask_notebook.stream(student, notebook.id, "Q?")
    async for event in events:
        if event.name == "delta":
            break
    await events.aclose()

    turn = await chat.ask_notebook.execute(student, notebook.id, "Next?")

    assert turn.user_message.seq == 3
    history = scripted_llm.text_requests[-1]["messages"]
    assert history[1] == {"role": "user", "content": "Q?"}
    assert history[2]["role"] == "assistant" and history[2]["content"].startswith(
        "Some"
    )


async def test_a_cancelled_request_stores_the_partial_answer(
    make_core: CoreFactory, student: Actor
) -> None:
    """NB-6: cancelling the task (a dropped connection) keeps what was streamed."""
    gated = GatedLlm()
    live = make_core(gateway=gated)
    chat = build_chat(live)
    notebook, _ = await notebook_with_source(live, student)
    seen: list[StreamEvent] = []

    async def consume() -> None:
        async for event in chat.ask_notebook.stream(student, notebook.id, "Q?"):
            seen.append(event)

    task = asyncio.create_task(consume())
    for _ in range(300):
        if any(e.name == "delta" for e in seen):
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    stored = await thread(live, student, notebook)
    assert [m.role for m in stored] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert stored[1].stopped is True
    assert stored[1].content.text == "Hello world."
    assert (await live.budget.usage(student.user_id)).day.used > 0
    gated.gate.set()
    retry = await chat.ask_notebook.execute(student, notebook.id, "Again?")
    assert retry.user_message.seq == 3


async def test_a_finished_stream_closed_at_done_is_not_stored_twice(
    core: NotebooksCore, chat: ChatServices, student: Actor, scripted_llm: ScriptedLlm
) -> None:
    """NB-6: closing the stream at `done` must not add a stopped copy."""
    notebook, _ = await notebook_with_source(core, student)
    scripted_llm.queue_stream(STREAMED)
    events = chat.ask_notebook.stream(student, notebook.id, "Q?")

    async for event in events:
        if event.name == "done":
            break
    await events.aclose()

    stored = await thread(core, student, notebook)
    assert [m.role for m in stored] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert stored[1].stopped is False
