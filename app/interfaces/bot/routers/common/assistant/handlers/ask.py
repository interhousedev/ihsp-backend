"""Free text (or a captioned photo or document): one request to the assistant."""

from typing import Any

from app.interfaces.bot.assistant.deliver import deliver
from app.interfaces.bot.assistant.media import upload_media
from app.interfaces.bot.assistant.service import bot_assistant, has_assistant_role
from app.interfaces.bot.assistant.stream import AnswerStream
from app.modules.ai.domain.errors import WrongAssistantError
from app.shared.actor import Actor
from app.shared.i18n.core import I18nContext

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.types import Message


async def ask(
    message: Message, bot: Bot, actor: Actor, container: Any, i18n: I18nContext
) -> None:
    """Stream the assistant's answer to the message."""
    assistant = bot_assistant(container)
    if assistant is None:  # the router's filter keeps this from happening
        return
    if not has_assistant_role(actor):  # teachers only: no assistant on the web
        await message.answer(i18n("bot-ai-no-assistant"))
        return
    stream = AnswerStream(
        bot,
        message.chat.id,
        message.message_id,
        drafts=message.chat.type == ChatType.PRIVATE,
    )
    await stream.typing()
    text = (message.text or message.caption or "").strip()
    file_ids = await upload_media(bot, message, actor, assistant.files)
    try:
        chat_id, events = await assistant.ask(actor, text, file_ids)
    except WrongAssistantError:  # the role changed while the chat was open
        await message.answer(i18n("bot-ai-no-assistant"))
        return
    await deliver(
        bot,
        stream,
        events,
        assistant=assistant,
        user_id=actor.user_id,
        chat_id=chat_id,
        i18n=i18n,
    )
