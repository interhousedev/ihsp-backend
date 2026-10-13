"""AI-EFF-3: the history limit and the `read_chat_history` tool of every assistant."""

import json
from typing import Any

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import ChatMessage, MessageContent, MessageRole
from app.shared.ids import new_id
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import text_reply, tool_reply

import pytest


def seed(h: AiHarness, chat_id: Any, count: int) -> None:
    """Fill a chat with alternating user and assistant messages."""
    h.store.messages[chat_id] = [
        ChatMessage(
            id=new_id(),
            chat_id=chat_id,
            seq=seq,
            role=MessageRole.USER if seq % 2 else MessageRole.ASSISTANT,
            content=MessageContent(text=f"msg-{seq:03d}"),
            created_at=h.clock.now(),
        )
        for seq in range(1, count + 1)
    ]


async def history_result(h: AiHarness, args: dict[str, Any]) -> dict[str, Any]:
    """Let the model call read_chat_history in a seeded chat; return its result."""
    chat = await h.new_chat()
    seed(h, chat.id, 10)
    h.llm.push(tool_reply(("read_chat_history", args)), text_reply("done"))
    await h.say(chat.id, "what did I ask first?")
    sent = json.loads(h.llm.requests[-1]["messages"][-1]["content"])
    result: dict[str, Any] = sent["untrusted_data"]
    return result


@pytest.mark.parametrize("assistant", [Assistant.STUDENT, Assistant.ADMIN])
async def test_every_assistant_has_the_history_tool(
    h: AiHarness, assistant: Assistant
) -> None:
    """AI-EFF-3: the model can fetch older messages on demand."""
    actor = h.student if assistant is Assistant.STUDENT else h.admin
    chat = await h.new_chat(assistant=assistant)
    h.llm.push(text_reply("ok"))
    await h.say(chat.id, "hi", actor=actor)

    names = {t["function"]["name"] for t in h.llm.requests[-1]["tools"]}
    assert "read_chat_history" in names


async def test_the_oldest_messages_are_read_by_offset(h: AiHarness) -> None:
    """AI-EFF-3: offset counts back from the newest message; oldest first."""
    result = await history_result(h, {"offset": 8, "limit": 3})

    assert [m["text"] for m in result["messages"]] == ["msg-001", "msg-002", "msg-003"]
    assert result["total"] == 11


async def test_a_query_filters_the_messages(h: AiHarness) -> None:
    """AI-EFF-3: a word search over the chat, newest matches first, bounded."""
    result = await history_result(h, {"query": "MSG-00", "limit": 2})

    assert [m["seq"] for m in result["messages"]] == [8, 9]


async def test_the_limit_is_bounded(h: AiHarness) -> None:
    """AI-EFF-3: one call reads at most 20 messages."""
    chat = await h.new_chat()
    h.llm.push(tool_reply(("read_chat_history", {"limit": 500})), text_reply("x"))
    await h.say(chat.id, "go")

    sent = h.llm.requests[-1]["messages"][-1]["content"]
    assert "error" in sent


async def test_the_history_limit_setting_cuts_the_request(
    make_harness: HarnessFactory,
) -> None:
    """AI-EFF-3: `ai_chat_history_limit` messages go in full, older ones summarised."""
    h = make_harness(limits={"ai_chat_history_limit": 6})
    chat = await h.new_chat()
    seed(h, chat.id, 30)
    h.llm.push(text_reply("SUMMARY"), text_reply("answer"))

    await h.say(chat.id, "next")

    answer = h.llm.requests[-1]["messages"]
    texts = [m["content"] for m in answer]
    assert "msg-024" not in "".join(texts)
    assert texts[-1] == "next" and "msg-030" in texts
    assert h.summaries.items[chat.id].upto_seq == 25
