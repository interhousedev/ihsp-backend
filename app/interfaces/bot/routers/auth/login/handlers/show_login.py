"""Any message or button from an unlinked account leads to Log in (BOT-5)."""

from app.interfaces.bot.screens.login import build_login
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message


async def show_login(
    request: Message | CallbackQuery,
    state: FSMContext,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Show the Log in button; ``/start <anything>`` behaves like ``/start``."""
    await state.clear()
    await show(request, build_login(i18n, services.urls))
