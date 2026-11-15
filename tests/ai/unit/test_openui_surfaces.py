"""AI-OPENUI: a scripted model through the real turn loop, on both surfaces.

Telegram: the block is a `show_ui_block` tool call and the stored answer has no code
fence; the bot appends the block to the end of its message. Web: the model writes the
block inline in a fenced ``openui`` block of the answer and the tool is not offered.
"""

from typing import Any, cast

from app.modules.ai.application.tools.show_ui_block import SHOW_UI_BLOCK
from app.modules.ai.domain.prompts import SURFACE_TELEGRAM
from app.settings import Settings
from tests.ai.conftest import AiHarness, HarnessFactory
from tests.fakes.ai.llm import text_reply, tool_reply

import pytest

VALID = 'root = Stack([chart])\nchart = BarChart(["Mon", "Tue"], [3, 5], "Marks")\n'
BROKEN = 'root = Stack([chart])\nchart = BarChart(["Mon", "Tue"])\n'


@pytest.fixture
def h(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, make_harness: HarnessFactory
) -> AiHarness:
    """A harness with OpenUI switched on."""
    monkeypatch.setattr(settings.ai, "openui_enabled", True)
    return make_harness()


def _names(tools: list[dict[str, Any]]) -> set[str]:
    return {str(cast(dict[str, Any], t.get("function", t))["name"]) for t in tools}


async def _send(h: AiHarness, text: str, surface: str) -> Any:
    chat = await h.new_chat()
    return await h.services.send_message.execute(
        actor=h.student, chat_id=chat.id, text=text, file_ids=[], surface=surface
    )


async def test_telegram_shows_a_block_through_the_tool(h: AiHarness) -> None:
    h.llm.push(
        tool_reply((SHOW_UI_BLOCK, {"block": VALID})),
        text_reply("Your marks are in the chart below."),
    )

    result = await _send(h, "chart of my marks", SURFACE_TELEGRAM)

    first = h.llm.requests[0]
    assert SHOW_UI_BLOCK in _names(first["tools"])
    assert "show_ui_block" in first["system"]
    assert "```openui" not in first["system"]
    calls = [c for m in result.new_messages for c in m.tool_calls]
    (call,) = [c for c in calls if c.tool == SHOW_UI_BLOCK]
    assert call.status == "done"
    assert call.ui_block is not None and "BarChart" in call.ui_block
    answer = result.new_messages[-1].text
    assert answer == "Your marks are in the chart below."
    assert "```" not in answer


async def test_telegram_tells_the_model_when_the_block_is_broken(h: AiHarness) -> None:
    """A broken block is a failed call: nothing to show, the model can fix it."""
    h.llm.push(
        tool_reply((SHOW_UI_BLOCK, {"block": BROKEN})),
        tool_reply((SHOW_UI_BLOCK, {"block": VALID})),
        text_reply("Here."),
    )

    result = await _send(h, "chart", SURFACE_TELEGRAM)

    calls = [c for m in result.new_messages for c in m.tool_calls]
    shown = [c.ui_block for c in calls if c.ui_block]
    assert len(calls) == 2 and len(shown) == 1


async def test_web_writes_the_block_inline_in_the_text(h: AiHarness) -> None:
    answer = f"Your marks:\n\n```openui\n{VALID}```\n\nWell done."
    h.llm.push(text_reply(answer))

    result = await _send(h, "chart of my marks", "web")

    request = h.llm.requests[0]
    assert SHOW_UI_BLOCK not in _names(request["tools"])
    assert "```openui" in request["system"]
    assert "show_ui_block" not in request["system"]
    stored = result.new_messages[-1].text
    assert f"```openui\n{VALID}```" in stored
    assert stored.index("Your marks:") < stored.index("BarChart")
    assert stored.index("BarChart") < stored.index("Well done.")
    assert not result.new_messages[-1].tool_calls


async def test_web_drops_a_block_that_cannot_be_repaired(h: AiHarness) -> None:
    h.llm.push(text_reply(f"Look:\n\n```openui\n{BROKEN}```\n\nDone."))

    result = await _send(h, "chart", "web")

    stored = result.new_messages[-1].text
    assert "Look:" in stored and "Done." in stored
    assert "BarChart" not in stored
