"""The per-chat menu button that opens the mini app (BOT-8)."""

from app.interfaces.bot.urls import BotUrls
from app.shared.contracts.identity import UserRef
from app.shared.i18n.core import I18nContext

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo

log = structlog.get_logger(__name__)


async def set_app_menu_button(
    bot: Bot, chat_id: int, user: UserRef, i18n: I18nContext, urls: BotUrls
) -> None:
    """Point the chat's menu button at IHSP Web (students) or the staff portal.

    Best effort: Telegram refuses non-HTTPS URLs outside its test environment, and
    that must not break the menu.
    """
    button = MenuButtonWebApp(
        text=i18n("bot-btn-open-app"),
        web_app=WebAppInfo(url=urls.app_for(user.roles)),
    )
    try:
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=button)
    except TelegramBadRequest as error:
        log.warning("bot.menu_button_failed", chat_id=chat_id, error=error.message)


async def reset_menu_button(bot: Bot, chat_id: int) -> None:
    """Restore the default menu button (after Log out)."""
    try:
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonDefault())
    except TelegramBadRequest as error:
        log.warning(
            "bot.menu_button_reset_failed", chat_id=chat_id, error=error.message
        )
