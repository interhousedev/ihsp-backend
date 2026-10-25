"""Unlink this Telegram account after the user confirmed (UF-BOT-10)."""

from app.interfaces.bot.screens.login import build_login
from app.interfaces.bot.services import BotServices
from app.interfaces.bot.utilities.menu_button import reset_menu_button
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.i18n.core import I18nContext

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery


async def logout(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
    services: BotServices,
    i18n: I18nContext,
) -> None:
    """Remove the link, clear the FSM state and offer Log in again."""
    await services.identity_commands.unlink_telegram(callback.from_user.id)
    await state.clear()
    await reset_menu_button(bot, callback.from_user.id)
    await show(callback, build_login(i18n, services.urls))
