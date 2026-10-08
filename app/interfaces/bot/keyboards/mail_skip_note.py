"""Keyboard of the optional forward note: Skip or Cancel."""

from app.interfaces.bot.callbacks import MailComposeCb
from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import CancelCb
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext) -> Rows:
    """Return Skip and Cancel."""
    return [
        [
            cb_button(i18n("bot-btn-skip"), MailComposeCb(action="skip")),
            cb_button(i18n("bot-btn-cancel"), CancelCb()),
        ]
    ]
