"""The /help screen: what the bot can do, the user's commands, the menu below."""

from app.interfaces.bot.keyboards import back_to_menu
from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.commands import COMMAND_KEYS, command_names_for
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_help(user: UserRef, i18n: I18nContext, urls: BotUrls) -> RenderedMessage:
    """Return the help text with the user's commands and the menu buttons."""
    commands = [
        f"/{name} \u2014 {i18n(COMMAND_KEYS[name])}"
        for name in command_names_for(user.roles)
        if name != "start"
    ]
    text = "\n".join([i18n("bot-help"), "", *commands])
    return RenderedMessage(text_html=text, buttons=back_to_menu.get(i18n))
