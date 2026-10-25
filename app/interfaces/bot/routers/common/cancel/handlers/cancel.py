"""Cancel the current input everywhere (BOT-4)."""

from dataclasses import replace

from app.interfaces.bot.screens.login import build_login
from app.interfaces.bot.screens.main_menu import build_main_menu
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message


async def cancel(
    request: Message | CallbackQuery,
    state: FSMContext,
    services: BotServices,
    i18n: I18nContext,
    user: UserRef | None = None,
) -> None:
    """Clear the FSM state and go back to the menu (or to Log in)."""
    await state.clear()
    if user is None:
        rendered = build_login(i18n, services.urls)
    else:
        menu = build_main_menu(user, i18n, services.urls)
        text = f"{i18n('bot-cancelled')}\n\n{menu.text_html}"
        rendered = replace(menu, text_html=text)
    await show(request, rendered)
