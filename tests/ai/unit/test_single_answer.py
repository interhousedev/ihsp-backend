"""One answer per turn: tool rounds and progress notes live in one message; SSE."""

from datetime import date
from uuid import uuid4

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.errors import ChatNotFoundError
from app.modules.ai.domain.prompts import system_prompt
from app.modules.ai.domain.tool_call import ToolStatus
from app.shared.agent_steps import StepKind
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply, tool_reply

import pytest


async def test_a_tool_loop_stores_one_answer_with_steps_and_notes(
    h: AiHarness,
) -> None:
    """Two tool rounds with notes: one assistant message, notes in its steps."""
    h.marks.summary = []
    chat = await h.new_chat()
    h.llm.push(
        tool_reply(("get_my_subjects", {}), text="Ищу ваши предметы."),
        tool_reply(("get_homework", {}), text="Нашёл. Теперь задания."),
        text_reply("Готово."),
    )

    result = await h.say(chat.id, "Что задано по литературе?")

    stored = h.store.chat_messages(chat.id)
    assert [m.role.value for m in stored] == ["user", "assistant"]
    answer = stored[1]
    assert answer.text == "Готово."
    assert answer.content.progress == ["Ищу ваши предметы.", "Нашёл. Теперь задания."]
    assert [c.round for c in answer.tool_calls] == [0, 1]
    assert [(s.kind, s.label) for s in answer.content.steps] == [
        (StepKind.THINK, "Ищу ваши предметы."),
        (StepKind.TOOL, "get_my_subjects"),
        (StepKind.THINK, "Нашёл. Теперь задания."),
        (StepKind.TOOL, "get_homework"),
    ]
    assert answer.tokens_in == 300
    assert [m.seq for m in result.new_messages] == [1, 2]
    # the model still sees each round with its own calls and results
    last = h.llm.requests[-1]["messages"]
    assert [m["role"] for m in last] == [
        *("user", "assistant", "tool", "assistant", "tool"),
    ]
    assert last[1]["content"] == "Ищу ваши предметы."
    assert last[3]["tool_calls"][0]["function"]["name"] == "get_homework"


async def test_after_an_approval_the_answer_grows_in_the_same_message(
    h: AiHarness,
) -> None:
    """The write's round and the answer after Approve share one message."""
    chat = await h.new_chat()
    h.llm.push(
        tool_reply(
            ("create_flashcard_set", {"title": "Bio", "cards": _cards()}),
            text="Создаю набор.",
        )
    )
    first = await h.say(chat.id, "Сделай карточки")
    call_id = first.new_messages[1].tool_calls[0].id
    h.llm.push(text_reply("Набор готов."))

    await h.services.approve_tool_call.execute(
        actor=h.student, chat_id=chat.id, call_id=call_id
    )

    stored = h.store.chat_messages(chat.id)
    assert len(stored) == 2
    assert stored[1].text == "Набор готов."
    assert stored[1].content.progress == ["Создаю набор."]
    assert stored[1].tool_calls[0].status is ToolStatus.DONE


async def test_the_stream_sends_status_steps_deltas_then_done(h: AiHarness) -> None:
    """Every round streams live; a round with tool calls ends with `round_end`."""
    h.marks.summary = []
    chat = await h.new_chat()
    h.llm.push(
        tool_reply(("get_my_subjects", {}), text="Ищу предметы."),
        text_reply("Два слова"),
    )

    events = [
        e
        async for e in h.services.send_message.stream(
            actor=h.student, chat_id=chat.id, text="Предметы?", file_ids=[]
        )
    ]

    names = [e.name for e in events]
    assert names[0] == "status"
    assert names[-1] == "done" and "error" not in names
    end = names.index("round_end")
    note = "".join(e.data["text"] for e in events[:end] if e.name == "delta")
    assert note == "Ищу предметы." == events[end].data["text"]
    assert end < names.index("step", end)  # the tool step follows the note
    answer = "".join(e.data["text"] for e in events[end:] if e.name == "delta")
    assert answer == "Два слова"
    statuses = [e.data["text"] for e in events if e.name == "status"]
    assert "Looked up your subjects" in statuses and "Ищу предметы." in statuses
    assert all(r.get("streamed") for r in h.llm.requests)
    done = events[-1].result
    assert done is not None and done.new_messages[-1].text == "Два слова"
    assert done.new_messages[-1].progress == ["Ищу предметы."]


async def test_regenerate_streams_too(h: AiHarness) -> None:
    """Regenerate shares the streamed loop (approve and reject do too)."""
    chat = await h.new_chat()
    h.llm.push(text_reply("first"))
    await h.say(chat.id, "hi")
    h.llm.push(text_reply("second answer"))

    events = [
        e
        async for e in h.services.regenerate_answer.stream(
            actor=h.student, chat_id=chat.id
        )
    ]

    assert [e.name for e in events][-1] == "done"
    deltas = "".join(e.data["text"] for e in events if e.name == "delta")
    assert deltas == "second answer"


async def test_a_refusal_raises_before_the_stream_starts(h: AiHarness) -> None:
    """An unknown chat is a plain error, not an event."""
    stream = h.services.send_message.stream(
        actor=h.student, chat_id=uuid4(), text="hi", file_ids=[]
    )
    with pytest.raises(ChatNotFoundError):
        await anext(stream)


def test_the_prompt_asks_for_the_language_of_the_user() -> None:
    """The answer and the progress notes follow the message language."""
    prompt = system_prompt(Assistant.STUDENT, "en", date(2026, 10, 16))

    assert "language of the user's last message" in prompt
    assert "progress" in prompt and "English" in prompt


def _cards() -> list[dict[str, str]]:
    return [{"front": "a", "back": "b"}, {"front": "c", "back": "d"}]
