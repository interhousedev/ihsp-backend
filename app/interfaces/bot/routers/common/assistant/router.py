"""Router of the assistant: free text of linked users, /new and approval buttons.

It sits just before the fallback router, so commands, screens, steps with a state
and the guest mode always win. Text that starts with "/" is never an AI request:
an unknown command gets the fallback hint.
"""

from typing import Any

from app.interfaces.bot.assistant.deliver import AiCallCb, AiVizCb
from app.interfaces.bot.assistant.service import bot_assistant
from app.interfaces.bot.filters.is_linked import IsLinked
from app.interfaces.bot.middlewares.bot_registry import BotAllows
from app.interfaces.bot.routers.common.assistant.handlers.ask import ask
from app.interfaces.bot.routers.common.assistant.handlers.decide import decide
from app.interfaces.bot.routers.common.assistant.handlers.delete_chat import (
    AiDeleteCb,
    confirm_delete,
    delete_chat,
)
from app.interfaces.bot.routers.common.assistant.handlers.new_chat import new_chat
from app.interfaces.bot.routers.common.assistant.handlers.visualize import (
    visualize,
)
from app.interfaces.bot.routers.common.assistant.handlers.voice import ask_voice
from app.modules.admin.domain.telegram_bot import BotFeature

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
    router.message.filter(IsLinked(), HasAssistant(), BotAllows(BotFeature.AI_AGENT))
    router.callback_query.filter(
        IsLinked(), HasAssistant(), BotAllows(BotFeature.AI_AGENT)
    )
    router.message.register(new_chat, Command("new"))
    router.message.register(delete_chat, Command("delete"))
    idle = StateFilter(None)
    router.message.register(ask, idle, F.text, ~F.text.startswith("/"))
    router.message.register(ask, idle, F.caption, F.photo | F.document)
    router.message.register(ask_voice, idle, F.voice | F.audio | F.video | F.video_note)
    router.callback_query.register(decide, AiCallCb.filter())
    router.callback_query.register(confirm_delete, AiDeleteCb.filter())
    router.callback_query.register(visualize, AiVizCb.filter())
    return router
