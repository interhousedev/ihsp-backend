"""Messages sent when a Telegram account gets linked (UF-BOT-01)."""

from app.interfaces.bot.keyboards import security_link
from app.interfaces.bot.screens.main_menu import build_main_menu
from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_linked_here(
    user: UserRef, i18n: I18nContext, urls: BotUrls
) -> RenderedMessage:
    """The linked account itself: Logged in as ..., then the main menu."""
    return build_main_menu(user, i18n, urls, intro_key="bot-linked-as")


def build_linked_elsewhere(
    username: str | None, i18n: I18nContext, urls: BotUrls
) -> RenderedMessage:
    """Another channel of the user: a Telegram account was linked, with Not me."""
    who = f"@{escape(username)}" if username else i18n("bot-linked-unknown")
    return RenderedMessage(
        text_html=i18n("bot-linked-elsewhere", who=who),
        buttons=security_link.get(i18n, urls),
    )
