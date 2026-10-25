"""A message the bot did not expect: a short hint and the menu (BOT-23)."""

from app.interfaces.bot.keyboards import cancel
from app.interfaces.bot.screens.main_menu import build_main_menu
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

from aiogram.fsm.context import FSMContext
from aiogram.types import Message


async def show_hint(
    message: Message,
    state: FSMContext,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Without an active step show the menu; inside a step offer Cancel."""
    if await state.get_state() is None:
        menu = build_main_menu(
            user, i18n, services.urls, intro_key="bot-hint-unexpected"
        )
        await show(message, menu)
        return
    await show(
        message,
        RenderedMessage(text_html=i18n("bot-hint-in-state"), buttons=cancel.get(i18n)),
    )
