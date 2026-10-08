"""Keyboard with one button: open a lesson in the web app."""

from app.interfaces.bot.utilities.markup import Rows, web_app_button
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext, url: str) -> Rows:
    """Return the Open lesson row."""
    return [[web_app_button(i18n("bot-btn-open-lesson"), url)]]
