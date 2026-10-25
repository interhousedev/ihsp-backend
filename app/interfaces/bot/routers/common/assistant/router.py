"""Router of the assistant: free text of linked users, /new and approval buttons.

It sits just before the fallback router, so commands, screens, steps with a state
and the guest mode always win. Text that starts with "/" is never an AI request:
an unknown command gets the fallback hint.
"""

from typing import Any

from app.interfaces.bot.assistant.deliver import AiCallCb, AiVizCb
from app.interfaces.bot.assistant.service import bot_assistant
from app.interfaces.bot.filters.is_linked import IsLinked
from app.interfaces.bot.routers.common.assistant.handlers.ask import ask
from app.interfaces.bot.routers.common.assistant.handlers.decide import decide
from app.interfaces.bot.routers.common.assistant.handlers.new_chat import new_chat
from app.interfaces.bot.routers.common.assistant.handlers.visualize import (
    visualize,
)

from aiogram import F, Router
from aiogram.filters import Command, Filter, StateFilter
from aiogram.types import TelegramObject


class HasAssistant(Filter):
    """Passes when the process built the AI module."""

    async def __call__(self, event: TelegramObject, container: Any = None) -> bool:
        """Return True when there is an assistant to talk to."""
        return bot_assistant(container) is not None


def build_router() -> Router:
    """Build the assistant router."""
    router = Router(name="common.assistant")
    router.message.filter(IsLinked(), HasAssistant())
    router.callback_query.filter(IsLinked(), HasAssistant())
    router.message.register(new_chat, Command("new"))
    idle = StateFilter(None)
    router.message.register(ask, idle, F.text, ~F.text.startswith("/"))
    router.message.register(ask, idle, F.caption, F.photo | F.document)
    router.callback_query.register(decide, AiCallCb.filter())
    router.callback_query.register(visualize, AiVizCb.filter())
    return router
