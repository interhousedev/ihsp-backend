"""The system prompt of a chat's next model request."""

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat import Chat
from app.modules.ai.domain.prompts import system_prompt
from app.modules.ai.domain.prompts_author import author_system_prompt, course_context
from app.modules.ai.ports.author_gate import AuthorGate
from app.shared.clock import Clock, local_today


class SystemPrompts:
    """Builds the instructions for a chat; author chats get their course context.

    The course context (title, description, the draft outline with ids) is read
    again before every model request, so the model sees what it has just created.
    It costs one small LMS read and saves the model a tool round.
    """

    def __init__(self, gate: AuthorGate, clock: Clock) -> None:
        """Store the course gate (for the outline) and the clock (for the date)."""
        self.gate = gate
        self.clock = clock

    async def build(self, chat: Chat, locale: str) -> str:
        """Return the system prompt of the chat's assistant in the user's locale."""
        today = local_today(self.clock)
        if chat.assistant is not Assistant.LMS_AUTHOR or chat.scope is None:
            return system_prompt(chat.assistant, locale, today)
        brief = await self.gate.course_brief(chat.scope.course_id)
        return author_system_prompt(locale, today, course_context(brief))
