"""Keyboard with one button: cancel the current input."""

from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import CancelCb
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext) -> Rows:
    """Return the Cancel button row (every multi-step input has one, BOT-4)."""
    return [[cb_button(i18n("bot-btn-cancel"), CancelCb())]]
