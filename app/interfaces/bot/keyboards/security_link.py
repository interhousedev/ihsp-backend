"""Keyboard with one link to the security settings of the ID service."""

from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.markup import Rows, url_button
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext, urls: BotUrls) -> Rows:
    """Return the Not me / Security settings row (a plain link, UF-BOT-01)."""
    return [[url_button(i18n("bot-btn-security"), urls.security)]]
