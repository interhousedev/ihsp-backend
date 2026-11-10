"""The Assistant hub entry."""

from app.interfaces.bot.screens.assistant_hint import build_assistant_hint
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery


async def show_assistant(
    callback: CallbackQuery, user: UserRef, services: BotServices, i18n: I18nContext
) -> None:
    """Tell the user how to ask the assistant in this chat."""
    await show(callback, build_assistant_hint(user, i18n, services.urls))
