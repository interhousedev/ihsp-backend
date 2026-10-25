"""The main menu: /start, /menu and the Back buttons (BOT-6, BOT-9)."""

from app.interfaces.bot.screens.main_menu import build_main_menu
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.menu_button import set_app_menu_button
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

from aiogram import Bot
from aiogram.types import CallbackQuery, Message


async def show_menu(
    request: Message | CallbackQuery,
    bot: Bot,
    user: UserRef,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Show the menu; commands also point the chat's menu button at the app."""
    unread = await services.notify.unread_count(user.id)
    await show(request, build_main_menu(user, i18n, services.urls, unread=unread))
    if isinstance(request, Message):
        await set_app_menu_button(bot, request.chat.id, user, i18n, services.urls)
