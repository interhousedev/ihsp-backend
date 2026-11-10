"""The footer every sub-screen ends with: ← Back to the parent and ⌂ Menu."""

from app.interfaces.bot.utilities.markup import Button, Rows, cb_button
from app.shared.contracts.callbacks import MenuCb
from app.shared.i18n.core import I18nContext

from aiogram.filters.callback_data import CallbackData


def menu_button(i18n: I18nContext) -> Button:
    """The ⌂ Menu button that opens the hub."""
    return cb_button(i18n("bot-btn-menu"), MenuCb(screen="menu"))


def nav_rows(i18n: I18nContext, parent: CallbackData | None = None) -> Rows:
    """Return ``[← Back, ⌂ Menu]``; Back goes to the hub when no parent is given."""
    back = parent if parent is not None else MenuCb(screen="menu")
    return [[cb_button(i18n("bot-btn-back"), back), menu_button(i18n)]]
