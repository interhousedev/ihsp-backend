"""Keyboard with the Log in button that opens the login mini app (ID-19)."""

from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.markup import Rows, web_app_button
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext, urls: BotUrls) -> Rows:
    """Return the Log in row; it must be an inline web_app button (initData)."""
    return [[web_app_button(i18n("bot-btn-login"), urls.login)]]
