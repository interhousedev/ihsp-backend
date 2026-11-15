"""/delete in a topic: confirm with buttons, then delete the AI chat and its topic."""

from typing import Any

from app.interfaces.bot.assistant.service import bot_assistant
from app.interfaces.bot.assistant.topics import thread_of
from app.interfaces.bot.utilities.reply_edit import answer_callback
from app.shared.actor import Actor
from app.shared.i18n.core import I18nContext

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

DELETE_CALL = "delete"


class AiDeleteCb(CallbackData, prefix="aid"):
    """Confirm (ok) or cancel the deletion of a chat; token from the store."""

    token: str
    ok: bool


async def delete_chat(
    message: Message, actor: Actor, container: Any, i18n: I18nContext
) -> None:
    """Ask before deleting the chat of the topic the command was sent in."""
    assistant = bot_assistant(container)
    if assistant is None:
        return
    thread = thread_of(message)
    mapped = (
        None
        if thread is None
        else await assistant.ai.telegram_topics.of_thread(message.chat.id, thread)
    )
    if mapped is None:
        await message.answer(i18n("bot-ai-delete-outside"))
        return
    token = await assistant.store.remember_call(
        actor.user_id, mapped.chat_id, DELETE_CALL
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n("bot-ai-delete-yes"),
                    callback_data=AiDeleteCb(token=token, ok=True).pack(),
                ),
                InlineKeyboardButton(
                    text=i18n("bot-ai-cancel"),
                    callback_data=AiDeleteCb(token=token, ok=False).pack(),
                ),
            ]
        ]
    )
    await message.answer(i18n("bot-ai-delete-confirm"), reply_markup=keyboard)


async def confirm_delete(
    callback: CallbackQuery,
    callback_data: AiDeleteCb,
    bot: Bot,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """Yes: delete the chat and the topic; Cancel: keep both."""
    assistant = bot_assistant(container)
    found = (
        None
        if assistant is None
        else await assistant.store.take_call(callback_data.token, actor.user_id)
    )
    origin = callback.message
    if assistant is None or found is None or not isinstance(origin, Message):
        await answer_callback(callback, i18n("bot-stale-button"))
        return
    await answer_callback(callback)
    chat_id, _ = found
    if not callback_data.ok:
        await origin.edit_text(i18n("bot-ai-delete-cancelled"), reply_markup=None)
        return
    topic = await assistant.ai.telegram_topics.of_chat(chat_id)
    await assistant.ai.delete_chat.execute(actor=actor, chat_id=chat_id)
    await assistant.ai.telegram_topics.unlink(chat_id)
    if await assistant.store.chat_of(actor.user_id) == chat_id:
        await assistant.store.forget_chat(actor.user_id)
    if topic is not None:
        try:
            await bot.delete_forum_topic(origin.chat.id, topic.message_thread_id)
            return
        except TelegramAPIError:
            pass  # the topic stays; say that the chat is gone
    await origin.edit_text(i18n("bot-ai-delete-done"), reply_markup=None)
