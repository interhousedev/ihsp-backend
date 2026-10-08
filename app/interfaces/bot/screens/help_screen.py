"""The /help screen: what the bot can do, with the menu below."""

from app.interfaces.bot.keyboards import main_menu
from app.interfaces.bot.urls import BotUrls
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_help(user: UserRef, i18n: I18nContext, urls: BotUrls) -> RenderedMessage:
    """Return the help text and the menu buttons of the user's roles."""
    return RenderedMessage(
        text_html=i18n("bot-help"), buttons=main_menu.get(i18n, user.roles, urls)
    )
