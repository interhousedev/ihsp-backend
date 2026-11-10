"""Keyboard of the teacher's Today screen."""

from app.interfaces.bot.utilities.markup import Rows, cb_button, web_app_button
from app.interfaces.bot.utilities.navigation import nav_rows
from app.shared.contracts.callbacks import MenuCb
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext, app_url: str) -> Rows:
    """Return Current lesson, Open in app and the navigation footer."""
    return [
        [cb_button(i18n("bot-btn-current-lesson"), MenuCb(screen="lesson"))],
        [web_app_button(i18n("bot-btn-open-in-app"), app_url)],
        *nav_rows(i18n),
    ]
