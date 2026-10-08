"""AI-9: trimming long chats to a window plus a summary; rebuilding tool messages."""

import json
from datetime import UTC, datetime

from app.modules.ai.domain.chat import ChatMessage, MessageContent, MessageRole
from app.modules.ai.domain.history import (
    MAX_HISTORY_CHARS,
    select_window,
    to_llm_messages,
)
from app.modules.ai.domain.tool_call import ToolAccess, ToolCall, ToolStatus
from app.shared.ids import new_id
from tests.ai.conftest import AiHarness
from tests.fakes.ai.llm import text_reply

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def message(
    seq: int, role: MessageRole, text: str = "", **kwargs: object
) -> ChatMessage:
    """A stored message."""
    return ChatMessage(
        id=new_id(),
        chat_id=new_id(),
        seq=seq,
        role=role,
        content=MessageContent(text=text or f"m{seq}"),
        created_at=NOW,
        **kwargs,  # type: ignore[arg-type]
    )


def call(status: ToolStatus, **kwargs: object) -> ToolCall:
    """A tool call in a state."""
    return ToolCall(
        id=f"c-{status.value}",
        tool="get_marks",
        access=ToolAccess.READ,
        args={"a": 1},
        status=status,
        **kwargs,  # type: ignore[arg-type]
    )


def test_every_call_gets_a_tool_message_in_the_right_shape() -> None:
    """AI-4: results of every state become tool messages; real output is wrapped."""
    calls = [
        call(ToolStatus.DONE, result={"x": 1}),
        call(ToolStatus.FAILED, error="boom"),
        call(ToolStatus.REJECTED, reject_reason="no"),
        call(ToolStatus.SUPERSEDED),
        call(ToolStatus.EXPIRED),
    ]
    messages = [
        message(1, MessageRole.USER),
        message(2, MessageRole.ASSISTANT, tool_calls=calls),
    ]

    built = to_llm_messages(messages)

    assert [m["role"] for m in built] == ["user", "assistant", *["tool"] * 5]
    assert [t["tool_call_id"] for t in built[2:]] == [c.id for c in calls]
    bodies = [json.loads(t["content"]) for t in built[2:]]
    assert bodies[0] == {"untrusted_data": {"x": 1}}
    assert bodies[1] == {"error": "boom"}
    assert bodies[2] == {"rejected": True, "reason": "no"}
    assert "superseded" in bodies[3]["error"] and "24 hours" in bodies[4]["error"]
    assert json.loads(built[1]["tool_calls"][0]["function"]["arguments"]) == {"a": 1}


def test_huge_results_are_truncated_inside_the_wrapper() -> None:
    """AI-9: one giant tool result cannot blow up the request."""
    huge = call(ToolStatus.DONE, result={"text": "x" * 50_000})

    built = to_llm_messages([message(1, MessageRole.ASSISTANT, tool_calls=[huge])])

    body = json.loads(built[1]["content"])
    assert body["untrusted_data"]["truncated"] is True
    assert len(built[1]["content"]) < 13_000


def test_summary_is_put_before_the_first_user_message() -> None:
    """AI-9: the summary is a context block at the start of the history."""
    built = to_llm_messages([message(31, MessageRole.USER, "hello")], "earlier: X")

    assert built[0]["role"] == "user"
    assert "earlier: X" in built[0]["content"] and built[0]["content"].endswith("hello")


def test_window_starts_at_a_user_message() -> None:
    """AI-9: a window never starts with an orphaned assistant reply."""
    tail = [
        message(1, MessageRole.USER),
        message(2, MessageRole.ASSISTANT),
        message(3, MessageRole.ASSISTANT),
        message(4, MessageRole.USER),
    ]

    assert [m.seq for m in select_window(tail, after_seq=2)] == [1, 2, 3, 4]
    assert [m.seq for m in select_window(tail, after_seq=3)] == [4]


def test_window_is_shrunk_to_the_size_cap() -> None:
    """AI-9: old messages are dropped when the history is too big."""
    big = "x" * (MAX_HISTORY_CHARS // 2 + 1)
    tail = [
        message(1, MessageRole.USER, big),
        message(2, MessageRole.ASSISTANT, big),
        message(3, MessageRole.USER, "now"),
    ]

    assert [m.seq for m in select_window(tail, after_seq=0)] == [3]


async def seed_messages(h: AiHarness, chat_id: object, count: int) -> None:
    """Fill a chat with alternating user and assistant messages."""
    uow = h.services.send_message.uow_factory()
    async with uow:
        for seq in range(1, count + 1):
            role = MessageRole.USER if seq % 2 else MessageRole.ASSISTANT
            await uow.messages.add(
                ChatMessage(
                    id=new_id(),
                    chat_id=chat_id,  # type: ignore[arg-type]
                    seq=seq,
                    role=role,
                    content=MessageContent(text=f"msg-{seq:03d}"),
                    created_at=NOW,
                )
            )
        await uow.commit()


async def test_long_chat_gets_one_summary_then_reuses_it(h: AiHarness) -> None:
    """AI-9: past 30 messages one extra request summarizes the older ones."""
    chat = await h.new_chat()
    await seed_messages(h, chat.id, 40)
    h.llm.push(text_reply("SUMMARY TEXT"), text_reply("answer"))

    await h.say(
        chat.id, "continue"
    )  # seq 41 -> messages 1..11 are older than the window

    summarize, answer = h.llm.requests
    assert "summarize a conversation" in summarize["system"]
    assert summarize["tools"] == []
    stored = h.summaries.items[chat.id]
    assert (stored.text, stored.upto_seq) == ("SUMMARY TEXT", 11)
    first = answer["messages"][0]["content"]
    assert "SUMMARY TEXT" in first and "msg-011" in first  # the turn's user message
    assert "msg-010" not in first

    h.llm.requests.clear()
    await h.say(chat.id, "again")
    assert len(h.llm.requests) == 1  # fewer than 20 new messages: no new summary


async def test_summary_is_recomputed_every_twenty_messages(h: AiHarness) -> None:
    """AI-9: the stored summary is refreshed after 20 more messages."""
    chat = await h.new_chat()
    await seed_messages(h, chat.id, 40)
    h.llm.push(text_reply("S1"), text_reply("a"))
    await h.say(chat.id, "m")
    await seed_more(h, chat.id, 20)
    h.llm.push(text_reply("S2"), text_reply("b"))

    await h.say(chat.id, "n")

    assert h.summaries.items[chat.id].text == "S2"
    assert h.summaries.items[chat.id].upto_seq > 11


async def seed_more(h: AiHarness, chat_id: object, count: int) -> None:
    """Append `count` more messages after the last one."""
    uow = h.services.send_message.uow_factory()
    async with uow:
        start = await uow.messages.last_seq(chat_id)  # type: ignore[arg-type]
        for seq in range(start + 1, start + count + 1):
            role = MessageRole.USER if seq % 2 else MessageRole.ASSISTANT
            await uow.messages.add(
                ChatMessage(
                    id=new_id(),
                    chat_id=chat_id,  # type: ignore[arg-type]
                    seq=seq,
                    role=role,
                    content=MessageContent(text=f"extra {seq}"),
                    created_at=NOW,
                )
            )
        await uow.commit()
