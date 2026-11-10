"""The Assistant entry of the hub: how to talk to the assistant in this chat."""

from app.interfaces.bot.keyboards import back_to_menu
from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.markup import web_app_button
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_assistant_hint(
    user: UserRef, i18n: I18nContext, urls: BotUrls
) -> RenderedMessage:
    """Explain that any text is a question; offer the full assistant in the app."""
    text = "\n\n".join(
        [
            f"<b>{i18n('bot-assistant-title')}</b>",
            i18n("bot-assistant-hint"),
            f"<i>{i18n('bot-assistant-footer')}</i>",
        ]
    )
    app = web_app_button(
        i18n("bot-btn-open-in-app"), urls.page(user.roles, "assistant/")
    )
    return RenderedMessage(text_html=text, buttons=[[app], *back_to_menu.get(i18n)])
