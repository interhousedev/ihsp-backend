"""Keyboard of the teacher's Today screen."""

from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import MenuCb
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext) -> Rows:
    """Return Current lesson and Back."""
    return [
        [cb_button(i18n("bot-btn-current-lesson"), MenuCb(screen="lesson"))],
        [cb_button(i18n("bot-btn-back"), MenuCb(screen="menu"))],
    ]
