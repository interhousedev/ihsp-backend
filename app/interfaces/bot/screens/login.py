"""The screen for an unlinked Telegram account: Log in (BOT-5)."""

from app.interfaces.bot.keyboards import login
from app.interfaces.bot.urls import BotUrls
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_login(i18n: I18nContext, urls: BotUrls) -> RenderedMessage:
    """Return the welcome text and the Log in mini app button."""
    return RenderedMessage(
        text_html=i18n("bot-login-welcome"), buttons=login.get(i18n, urls)
    )
