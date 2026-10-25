"""Ask for confirmation before unlinking this Telegram account (BOT-7)."""

from app.interfaces.bot.screens.logout_confirm import build_logout_confirm
from app.interfaces.bot.utilities.reply_edit import show
from app.shared.i18n.core import I18nContext

from aiogram.types import CallbackQuery


async def ask_logout(callback: CallbackQuery, i18n: I18nContext) -> None:
    """Warn that OTP codes and notifications stop on this Telegram account."""
    await show(callback, build_logout_confirm(i18n))
