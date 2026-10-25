"""A button nothing handles (an old message): say so instead of spinning."""

from app.interfaces.bot.utilities.reply_edit import answer_callback
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery


async def stale_button(callback: CallbackQuery, i18n: I18nContext) -> None:
    """Answer with a short note that the button is out of date."""
    await answer_callback(callback, i18n("bot-stale-button"))
