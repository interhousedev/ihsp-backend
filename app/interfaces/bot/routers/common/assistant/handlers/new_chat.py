"""/new: the next message starts a new conversation with the assistant."""

from typing import Any

from app.interfaces.bot.assistant.service import bot_assistant
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import Message


async def new_chat(
    message: Message, user: UserRef, container: Any, i18n: I18nContext
) -> None:
    """Forget the ongoing chat (it stays in the web chat list)."""
    assistant = bot_assistant(container)
    if assistant is not None:
        await assistant.store.forget_chat(user.id)
    await message.answer(i18n("bot-ai-new-chat"))
