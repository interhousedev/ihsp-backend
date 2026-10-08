"""Keyboard of the Marks screen: Open grades and Back."""

from app.interfaces.bot.utilities.markup import Rows, cb_button, web_app_button
from app.shared.contracts.callbacks import MenuCb
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext, grades_url: str) -> Rows:
    """Return the Open grades row and Back."""
    return [
        [web_app_button(i18n("bot-btn-open-grades"), grades_url)],
        [cb_button(i18n("bot-btn-back"), MenuCb(screen="menu"))],
    ]
