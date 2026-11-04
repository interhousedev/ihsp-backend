"""AI-OPENUI: `IHSP_AI__OPENUI_ENABLED` decides whether chat prompts teach blocks.

The student assistant serves the web chat and the Telegram bot alike, and the
Administration assistant has the same switch. The guest assistant (posts) has its own
fixed system prompt and never receives the OpenUI rules.
"""

from datetime import date
from typing import Any, cast
from uuid import uuid4

import app.modules.ai.wiring as ai_wiring
from app.modules.ai.application.system_prompts import SystemPrompts
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat
from app.modules.ai.domain.prompts import system_prompt
from app.modules.ai.ports.author_gate import AuthorGate
from app.modules.notebooks.domain.enums import ChatLength, ChatStyle
from app.modules.notebooks.domain.prompts.chat import chat_system_prompt
from app.settings import Settings
from app.shared.openui.prompt import openui_prompt
from tests.fakes.clock import FixedClock

import pytest

MARKER = "## Visual blocks"


class NoCourseGate:
    async def course_brief(self, course_id: Any) -> None:
        return None


GATE = cast(AuthorGate, NoCourseGate())


def chat_for(assistant: Assistant, clock: FixedClock) -> Chat:
    return Chat(
        id=uuid4(),
        owner_id=uuid4(),
        assistant=assistant,
        title="t",
        model="m",
        last_message_at=clock.now(),
    )


@pytest.mark.parametrize("assistant", [Assistant.STUDENT, Assistant.ADMIN])
async def test_flag_on_appends_the_block_rules_to_the_prompt(
    assistant: Assistant,
) -> None:
    """AI-OPENUI: web and bot chats get the OpenUI section only when the flag is on."""
    clock = FixedClock()
    chat = chat_for(assistant, clock)
    off = await SystemPrompts(GATE, clock, openui=False).build(chat, "en")
    on = await SystemPrompts(GATE, clock, openui=True).build(chat, "en")
    assert MARKER not in off
    assert MARKER in on
    assert on.replace(openui_prompt(), "") == off


async def test_flag_is_off_by_default() -> None:
    """AI-OPENUI: a SystemPrompts built without the flag never teaches blocks."""
    clock = FixedClock()
    prompt = await SystemPrompts(GATE, clock).build(
        chat_for(Assistant.STUDENT, clock), "ru"
    )
    assert MARKER not in prompt


async def test_wiring_passes_the_settings_flag_to_the_prompts(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, make_harness: Any
) -> None:
    """AI-OPENUI: the AI module wires `IHSP_AI__OPENUI_ENABLED` into SystemPrompts."""
    seen: list[bool] = []

    class Recording(SystemPrompts):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            seen.append(bool(kwargs.get("openui")))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ai_wiring, "SystemPrompts", Recording)
    monkeypatch.setattr(settings.ai, "openui_enabled", False)
    make_harness()
    monkeypatch.setattr(settings.ai, "openui_enabled", True)
    make_harness()
    assert seen == [False, True]


def test_tables_are_on_the_always_a_block_list_and_prose_stays_text() -> None:
    """AI-OPENUI: an asked-for table is a block; prose questions remain plain text."""
    prompt = " ".join(openui_prompt().split())
    assert "A requested table," in prompt
    assert "never a Markdown table" in prompt
    assert "Answer in text by default" in prompt
    assert "prose questions stay plain text" in prompt


def test_the_student_answer_starts_directly_without_meta_narration() -> None:
    """AI-OPENUI: the student prompt forbids describing the user or the tool choice."""
    prompt = " ".join(system_prompt(Assistant.STUDENT, date(2026, 11, 4)).split())
    assert "Begin with the answer itself" in prompt
    assert "Never describe the user or the request" in prompt
    assert "never mention tools" in prompt


def test_the_notebook_prompt_has_no_student_narration_rule() -> None:
    """The notebook chat keeps its own prompt: the student rule does not reach it."""
    prompt = chat_system_prompt(
        language="en",
        style=ChatStyle.DEFAULT,
        custom_prompt=None,
        length=ChatLength.DEFAULT,
        today=date(2026, 11, 4),
    )
    assert "Start the answer directly with its content" not in prompt
