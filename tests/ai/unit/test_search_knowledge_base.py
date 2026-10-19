"""The search_knowledge_base tool: gating, hits, no hits and a failing reporter."""

import json
from typing import Any

from app.modules.ai.domain.assistant import Assistant
from app.shared.contracts.school_knowledge import KnowledgeEntry
from tests.ai.conftest import AiHarness
from tests.ai.unit.test_tools_catalog import tools_of
from tests.fakes.ai.knowledge import FakeGapReporter, FakeKnowledgeLookup
from tests.fakes.ai.llm import text_reply, tool_reply

import pytest

TOOL = "search_knowledge_base"
ENTRY = KnowledgeEntry(
    "dress-code", "Dress code", "Uniform on weekdays.", ("rules",), 1
)


def bind(h: AiHarness, lookup: FakeKnowledgeLookup) -> FakeGapReporter:
    """Bind the fake lookup and reporter to the assistants."""
    reporter = FakeGapReporter()
    h.services.bindings.knowledge = lookup
    h.services.bindings.knowledge_gaps = reporter
    return reporter


async def call(h: AiHarness, query: str, assistant: Assistant) -> dict[str, Any]:
    """Let the model call the tool; return the result it receives."""
    actor = h.student if assistant is Assistant.STUDENT else h.admin
    chat = await h.new_chat(assistant=assistant)
    h.llm.push(tool_reply((TOOL, {"query": query})), text_reply("ok"))
    await h.say(chat.id, "go", actor=actor)
    sent: dict[str, Any] = json.loads(h.llm.requests[-1]["messages"][-1]["content"])
    return sent["untrusted_data"]


@pytest.mark.parametrize("assistant", [Assistant.STUDENT, Assistant.ADMIN])
async def test_the_tool_is_offered_to_student_and_admin(
    h: AiHarness, assistant: Assistant
) -> None:
    """Student and Administration assistants can search the knowledge base."""
    tools = await tools_of(h, assistant)

    assert TOOL in {t["function"]["name"] for t in tools}


async def test_the_author_assistant_has_no_such_tool(h: AiHarness) -> None:
    """The course author (and so every Studio task) never sees the tool."""
    registry = h.services.send_message.continue_turn.registry
    names = [t["function"]["name"] for t in registry.llm_tools(Assistant.LMS_AUTHOR)]

    assert TOOL not in names
    assert names  # the author does have tools


async def test_hits_come_back_with_key_title_value_and_tags(h: AiHarness) -> None:
    """Found entries are returned; nothing is reported."""
    lookup = FakeKnowledgeLookup([ENTRY])
    reporter = bind(h, lookup)

    data = await call(h, "uniform", Assistant.STUDENT)

    assert data["found"] is True
    assert data["items"] == [
        {
            "key": "dress-code",
            "title": "Dress code",
            "value": "Uniform on weekdays.",
            "tags": ["rules"],
        }
    ]
    assert lookup.queries == [("uniform", 5)]
    assert reporter.reports == []


async def test_no_hits_tells_the_model_and_reports_the_query(h: AiHarness) -> None:
    """An empty result says "do not invent" and reports query, chat kind, role."""
    reporter = bind(h, FakeKnowledgeLookup([]))

    data = await call(h, "who runs the chess club", Assistant.ADMIN)

    assert data["found"] is False and data["items"] == []
    assert "do not know" in data["note"] and "invent" in data["note"]
    [report] = reporter.reports
    assert report["query"] == "who runs the chess club"
    assert report["chat_kind"] == "admin" and report["user_role"] == "admin"
    assert report["chat_id"] is not None and report["notebook_id"] is None


async def test_a_failing_reporter_is_swallowed(h: AiHarness) -> None:
    """The answer does not depend on the report."""
    reporter = bind(h, FakeKnowledgeLookup([]))
    reporter.error = RuntimeError("notify is down")

    data = await call(h, "bus times", Assistant.STUDENT)

    assert data["found"] is False


async def test_an_unwired_knowledge_base_fails_like_a_tool(h: AiHarness) -> None:
    """Without the late binding the call fails; the chat goes on."""
    chat = await h.new_chat()
    h.llm.push(tool_reply((TOOL, {"query": "x"})), text_reply("ok"))

    result = await h.say(chat.id, "go")

    assert result.new_messages[1].tool_calls[0].status == "failed"
