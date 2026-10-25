"""The "See visualization" button: create the answer's 7-day share, then link it.

The share is made lazily on the first press of the owner (the token is
server-side and bound to the user); later presses reuse the same URL.
"""

from typing import Any

from app.interfaces.bot.assistant.deliver import AiVizCb
from app.interfaces.bot.assistant.service import bot_assistant
from app.interfaces.bot.utilities.reply_edit import answer_callback
from app.shared.actor import Actor
from app.shared.base_error import BaseError
from app.shared.i18n.core import I18nContext

import structlog
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

log = structlog.get_logger(__name__)


def _with_url(
    markup: InlineKeyboardMarkup | None, data: str, button: InlineKeyboardButton
) -> InlineKeyboardMarkup:
    """The message's keyboard with the pressed button replaced by the URL one."""
    rows = list(markup.inline_keyboard) if markup else []
    replaced = [
        [button if item.callback_data == data else item for item in row] for row in rows
    ]
    if not any(button in row for row in replaced):
        replaced.append([button])
    return InlineKeyboardMarkup(inline_keyboard=replaced)


async def visualize(
    callback: CallbackQuery,
    callback_data: AiVizCb,
    actor: Actor,
    container: Any,
    i18n: I18nContext,
) -> None:
    """Only the owner's press creates the share; others get the stale hint."""
    assistant = bot_assistant(container)
    found = (
        None
        if assistant is None
        else await assistant.store.visual_of(callback_data.token, actor.user_id)
    )
    if assistant is None or found is None:
        await answer_callback(callback, i18n("bot-stale-button"))
        return
    url = await assistant.store.visual_url(callback_data.token)
    if url is None:
        chat_id, seq = found
        try:
            view = await container.links.share_message.execute(
                actor, chat_id=chat_id, seq=seq
            )
        except BaseError as error:
            log.info("bot.ai.visualization_failed", error=type(error).__name__)
            await answer_callback(callback, i18n("bot-ai-visualization-failed"))
            return
        url = view.url
        expires = view.link.expires_at
        ttl = int((expires - view.link.created_at).total_seconds()) if expires else 1
        await assistant.store.set_visual_url(callback_data.token, url, ttl)
    await answer_callback(callback)
    origin = callback.message
    if isinstance(origin, Message):
        button = InlineKeyboardButton(text=i18n("bot-ai-visualization"), url=url)
        markup = _with_url(origin.reply_markup, callback.data or "", button)
        try:
            await origin.edit_reply_markup(reply_markup=markup)
        except TelegramBadRequest:
            log.info("bot.ai.visualization_edit_failed")
