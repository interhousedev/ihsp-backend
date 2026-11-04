"""The system prompt and the tools of each assistant, as a model request has them."""

from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from app.modules.ai.domain.assistant import Assistant
from app.modules.notebooks.domain.enums import ChatLength, ChatStyle
from app.modules.notebooks.domain.prompts.chat import chat_system_prompt
from app.modules.posts.application.guest_assistant import (
    GUEST_TOOLS,
    SYSTEM,
)
from app.shared.ai.answer_language import language_line
from app.shared.ai.prompt_cache import split_system, with_volatile_tail
from app.shared.openui.prompt import openui_prompt
from tests.ai.author_support import arrange
from tests.ai.conftest import AiHarness

TODAY: Final = date(2026, 11, 5)
ASSISTANTS: Final = ("student", "admin", "author", "notebook", "guest")
ASKED: Final = {
    "uz": "Fizikadan qanday baholarim bor?",
    "ru": "Какие у меня оценки по физике?",
    "en": "What are my physics marks?",
}
_CHAT_ASSISTANTS: Final = {"student": Assistant.STUDENT, "admin": Assistant.ADMIN}


@dataclass(frozen=True, slots=True)
class Request:
    """What the model receives before the messages."""

    system: str
    tools: list[dict[str, Any]]


def _notebook(language: str) -> str:
    """The notebook chat prompt with OpenUI on, as `AnswerPipeline` builds it."""
    prompt = chat_system_prompt(
        language=language,
        style=ChatStyle.DEFAULT,
        custom_prompt=None,
        length=ChatLength.DEFAULT,
        today=TODAY,
    )
    stable, tail = split_system(prompt)
    return with_volatile_tail(stable + openui_prompt(), tail)


async def request_of(
    h: AiHarness, name: str, language: str = "en", *, answer_now: bool = False
) -> Request:
    """The system prompt and tools of an assistant for a user of this language."""
    if name == "notebook":
        return Request(_notebook(language), [])
    if name == "guest":
        system = with_volatile_tail(SYSTEM, language_line(language))
        return Request(system, [dict(tool) for tool in GUEST_TOOLS])
    turn = h.services.send_message.continue_turn
    if name == "author":
        author = arrange(h)
        view = await author.chat()
        assistant = Assistant.LMS_AUTHOR
    else:
        assistant = _CHAT_ASSISTANTS[name]
        view = await h.new_chat(assistant=assistant)
    chat = h.store.chats[view.id]
    system = await turn.prompts.build(
        chat, language, last_user_text=ASKED[language], answer_now=answer_now
    )
    return Request(system, turn.registry.llm_tools(assistant, in_project=False))


def tool_names(request: Request) -> set[str]:
    """The names of the offered tools."""
    return {tool["function"]["name"] for tool in request.tools}
