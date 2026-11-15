"""The show_ui_block tool: checks a block, offered on the Telegram surface only."""

from typing import Any, cast
from uuid import uuid4

from app.modules.ai.application.system_prompts import SystemPrompts
from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.registry import ToolRegistry
from app.modules.ai.application.tools.show_ui_block import SHOW_UI_BLOCK, ShowUiBlock
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.prompts import SURFACE_TELEGRAM, TELEGRAM_RULES
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

import pytest

VALID = 'root = Stack([chart])\nchart = BarChart(["Mon", "Tue"], [3, 5], "Marks")\n'
BROKEN = 'root = Stack([chart])\nchart = BarChart(["Mon", "Tue"])\n'


def _ctx() -> ToolContext:
    actor = Actor(user_id=new_id(), roles=frozenset({Role.STUDENT}))
    return ToolContext(actor=actor, chat_id=new_id(), locale="en")


async def _run(block: str) -> dict[str, object]:
    tool = ShowUiBlock()
    return await tool.run(tool.parse({"block": block}), _ctx())


async def test_a_valid_block_is_returned_for_the_bot() -> None:
    result = await _run(VALID)
    assert result["shown"] is True
    assert "BarChart" in str(result["block"])


async def test_a_fence_around_the_block_is_removed() -> None:
    result = await _run(f"```openui\n{VALID}```")
    assert not str(result["block"]).startswith("`")
    assert "BarChart" in str(result["block"])


async def test_a_broken_block_fails_with_the_problems() -> None:
    with pytest.raises(ToolFailedError):
        await _run(BROKEN)


def _registry() -> ToolRegistry:
    return ToolRegistry([], [], telegram=[ShowUiBlock()])


def _names(tools: list[dict[str, object]]) -> set[str]:
    return {str(cast(dict[str, Any], t.get("function", t))["name"]) for t in tools}


def test_only_the_telegram_surface_is_offered_the_tool() -> None:
    registry = _registry()
    assert SHOW_UI_BLOCK in _names(
        registry.llm_tools(Assistant.STUDENT, surface=SURFACE_TELEGRAM)
    )
    assert SHOW_UI_BLOCK not in _names(registry.llm_tools(Assistant.STUDENT))
    assert registry.get(Assistant.STUDENT, SHOW_UI_BLOCK) is not None


class _Gate:
    async def course_brief(self, course_id: object) -> None:
        return None


async def test_the_telegram_prompt_has_no_web_only_instructions() -> None:
    clock = FixedClock()
    chat = Chat(
        id=uuid4(),
        owner_id=uuid4(),
        assistant=Assistant.STUDENT,
        title="t",
        model="m",
        last_message_at=clock.now(),
    )
    prompts = SystemPrompts(_Gate(), clock, openui=True)  # type: ignore[arg-type]
    telegram = await prompts.build(chat, "en", surface=SURFACE_TELEGRAM)
    web = await prompts.build(chat, "en")
    assert TELEGRAM_RULES in telegram
    assert SHOW_UI_BLOCK in telegram
    assert "```openui" not in telegram
    assert SHOW_UI_BLOCK not in web
    assert "Telegram" not in web
