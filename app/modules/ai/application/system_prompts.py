"""The system prompt of a chat's next model request."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat
from app.modules.ai.domain.project import project_block
from app.modules.ai.domain.prompts import (
    ANSWER_NOW,
    PRIORITIES,
    SURFACE_TELEGRAM,
    TELEGRAM_RULES,
    system_prompt,
)
from app.modules.ai.domain.prompts_author import (
    author_language_line,
    author_system_prompt,
    course_context,
)
from app.modules.ai.ports.author_gate import AuthorGate
from app.modules.ai.ports.unit_of_work import AiUnitOfWork
from app.shared.ai.answer_language import answer_language, language_line
from app.shared.ai.prompt_cache import with_volatile_tail
from app.shared.clock import Clock, local_today
from app.shared.limits import LimitsProvider
from app.shared.openui.prompt import openui_prompt

ProjectInstructions = Callable[[UUID], Awaitable[str]]


def project_instructions_from(
    uow_factory: Callable[[], AiUnitOfWork],
) -> ProjectInstructions:
    """A loader of a project's instructions ("" when the project is gone).

    It opens its own unit of work, so it is called between turns, never inside one.
    """

    async def load(project_id: UUID) -> str:
        async with uow_factory() as uow:
            project = await uow.projects.get(project_id)
        return project.instructions if project is not None else ""

    return load


class SystemPrompts:
    """Builds the instructions for a chat; author chats get their course context.

    The course context (title, description, the draft outline with ids) is read
    again before every model request, so the model sees what it has just created.
    It costs one small LMS read and saves the model a tool round.
    """

    def __init__(
        self,
        gate: AuthorGate,
        clock: Clock,
        limits: LimitsProvider | None = None,
        *,
        openui: bool = False,
        projects: ProjectInstructions | None = None,
    ) -> None:
        """Store the course gate (outline), the clock (date) and the runtime limits.

        `openui` adds the OpenUI block instructions (AI-OPENUI) to every assistant.
        `projects` gives the instructions of a chat's project, if it has one.
        """
        self.gate = gate
        self.clock = clock
        self.limits = limits
        self.openui = openui
        self.projects = projects

    async def build(
        self,
        chat: Chat,
        locale: str,
        *,
        surface: str = "web",
        last_user_text: str = "",
        answer_now: bool = False,
    ) -> str:
        """Return the system prompt of the chat's assistant.

        `surface` "telegram" adds the rich-formatting rules of the bot; the web prompt
        is returned unchanged. The language of `last_user_text` (else the locale) and
        `answer_now` (the last model request of a turn) go in a volatile tail after
        the cache breakpoint, so the stable part stays the same for everybody.
        """
        prompt = await self._base(chat)
        block = await self._project_block(chat)
        if block:
            prompt = f"{prompt}\n\n{block}"
        if surface == SURFACE_TELEGRAM:
            prompt = f"{prompt}\n\n{TELEGRAM_RULES}"
        if self.openui:
            prompt += openui_prompt()
        language = answer_language(last_user_text, locale)
        tail = [ANSWER_NOW] if answer_now else []
        if chat.assistant is Assistant.LMS_AUTHOR:
            if chat.scope is not None:
                brief = await self.gate.course_brief(chat.scope.course_id)
                tail.insert(0, course_context(brief))
            tail.append(author_language_line(language))
            return with_volatile_tail(prompt, "\n\n".join(tail))
        prompt = f"{prompt}\n\n{PRIORITIES}"
        tail.append(language_line(language))
        return with_volatile_tail(prompt, "\n".join(tail))

    async def _project_block(self, chat: Chat) -> str:
        if chat.project_id is None or self.projects is None:
            return ""
        return project_block(await self.projects(chat.project_id))

    async def _base(self, chat: Chat) -> str:
        today = local_today(self.clock)
        if chat.assistant is not Assistant.LMS_AUTHOR or chat.scope is None:
            ask = True
            if self.limits is not None:
                current = await self.limits.current()
                ask = bool(current.ai_ask_before_web_search)
            return system_prompt(chat.assistant, today, ask_before_web=ask)
        return author_system_prompt(today)
