"""The Telegram surface asks for rich formatting; the web prompt does not change.

The bot passes `surface="telegram"` to the turn; the web chat never does.
"""

from uuid import uuid4

from app.modules.ai.application.system_prompts import SystemPrompts
from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat
from app.modules.ai.domain.prompts import TELEGRAM_RULES
from tests.fakes.clock import FixedClock


class NoCourseGate:
    async def course_brief(self, course_id: object) -> None:
        return None


def _prompts(clock: FixedClock) -> SystemPrompts:
    return SystemPrompts(NoCourseGate(), clock)  # type: ignore[arg-type]


def _chat(assistant: Assistant, clock: FixedClock) -> Chat:
    return Chat(
        id=uuid4(),
        owner_id=uuid4(),
        assistant=assistant,
        title="t",
        model="m",
        last_message_at=clock.now(),
    )


async def test_the_web_prompt_is_unchanged_by_the_default_surface() -> None:
    clock = FixedClock()
    chat = _chat(Assistant.STUDENT, clock)
    prompts = _prompts(clock)
    web = await prompts.build(chat, "en")
    assert await prompts.build(chat, "en", surface="web") == web
    assert TELEGRAM_RULES not in web


async def test_the_telegram_prompt_keeps_the_web_text_and_adds_the_rules() -> None:
    clock = FixedClock()
    chat = _chat(Assistant.STUDENT, clock)
    prompts = _prompts(clock)
    web = await prompts.build(chat, "en")
    telegram = await prompts.build(chat, "en", surface="telegram")
    assert telegram.startswith(web)
    assert telegram.endswith(TELEGRAM_RULES)


def test_the_telegram_rules_are_short_and_name_the_rich_forms() -> None:
    assert len(TELEGRAM_RULES) < 400
    for form in ("bold", "list", "table", "link"):
        assert form in TELEGRAM_RULES
    assert "image" in TELEGRAM_RULES  # what Telegram cannot show
