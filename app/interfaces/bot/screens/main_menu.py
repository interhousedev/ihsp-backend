"""The main menu for the user's roles (BOT-9)."""

from app.interfaces.bot.keyboards import main_menu
from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_main_menu(
    user: UserRef,
    i18n: I18nContext,
    urls: BotUrls,
    *,
    unread: int = 0,
    intro_key: str = "bot-menu-greeting",
) -> RenderedMessage:
    """Greet the user and show the buttons of their roles."""
    lines = [
        i18n(intro_key, name=escape(user.first_name), login=escape(user.login or ""))
    ]
    if unread > 0:
        lines.append(i18n("bot-menu-unread", count=unread))
    return RenderedMessage(
        text_html="\n".join(lines), buttons=main_menu.get(i18n, user.roles, urls)
    )
