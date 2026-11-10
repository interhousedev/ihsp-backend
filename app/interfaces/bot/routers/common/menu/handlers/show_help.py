"""The /help command."""

from app.interfaces.bot.screens.help_screen import build_help
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery, Message


async def show_help(
    request: Message | CallbackQuery,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Explain the bot; Back leads to the hub."""
    await show(request, build_help(user, i18n, services.urls))
