"""The "See visualization" button: create the answer's 7-day share, then link it.

The share is made lazily on the first press of the owner (the token is
server-side and bound to the user); later presses reuse the same URL.
"""

from typing import Any

from app.interfaces.bot.assistant.deliver import AiVizCb
from app.interfaces.bot.assistant.service import bot_assistant
from app.interfaces.bot.assistant.visual import (
    VisualFailedError,
    VisualStaleError,
    visual_url,
)
from app.interfaces.bot.utilities.reply_edit import answer_callback
from app.shared.actor import Actor
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
    if assistant is None:
        await answer_callback(callback, i18n("bot-stale-button"))
        return
    try:
        url = await visual_url(assistant, container, actor, callback_data.token)
    except VisualStaleError:
        await answer_callback(callback, i18n("bot-stale-button"))
        return
    except VisualFailedError:
        await answer_callback(callback, i18n("bot-ai-visualization-failed"))
        return
    await answer_callback(callback)
    origin = callback.message
    if isinstance(origin, Message):
        button = InlineKeyboardButton(text=i18n("bot-ai-visualization"), url=url)
        markup = _with_url(origin.reply_markup, callback.data or "", button)
        try:
            await origin.edit_reply_markup(reply_markup=markup)
        except TelegramBadRequest:
            log.info("bot.ai.visualization_edit_failed")
