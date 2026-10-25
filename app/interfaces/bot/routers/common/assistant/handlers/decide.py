"""Approve or Cancel under a proposed write (a Studio output, a document, ...)."""

from typing import Any

from app.interfaces.bot.assistant.deliver import AiCallCb, deliver
from app.interfaces.bot.assistant.service import bot_assistant
from app.interfaces.bot.assistant.stream import AnswerStream
from app.interfaces.bot.utilities.reply_edit import answer_callback
from app.shared.actor import Actor
from app.shared.i18n.core import I18nContext

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message


async def decide(
    callback: CallbackQuery,
    callback_data: AiCallCb,
    bot: Bot,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """Run the decision; the assistant's follow-up is streamed like an answer."""
    assistant = bot_assistant(container)
    found = (
        None
        if assistant is None
        else await assistant.store.take_call(callback_data.token, actor.user_id)
    )
    if assistant is None or found is None:  # unknown, spent or someone else's
        await answer_callback(callback, i18n("bot-stale-button"))
        return
    await answer_callback(callback)
    origin = callback.message
    if isinstance(origin, Message):
        try:
            await origin.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass  # too old or unchanged: the buttons are spent anyway
    chat = callback.from_user.id if origin is None else origin.chat.id
    draft_id = (origin.message_id if origin is not None else 0) + 1
    stream = AnswerStream(bot, chat, draft_id)
    await stream.typing()
    chat_id, call_id = found
    events = await assistant.decide(actor, chat_id, call_id, approve=callback_data.ok)
    await deliver(
        bot,
        stream,
        events,
        assistant=assistant,
        user_id=actor.user_id,
        chat_id=chat_id,
        i18n=i18n,
    )
