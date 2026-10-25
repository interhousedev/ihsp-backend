"""Keyboard under an email draft: Send, Edit, Cancel (UF-MAIL-03)."""

from app.interfaces.bot.callbacks import MailComposeCb
from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import CancelCb
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext) -> Rows:
    """Return the preview buttons."""
    return [
        [
            cb_button(i18n("bot-btn-send"), MailComposeCb(action="send")),
            cb_button(i18n("bot-btn-edit"), MailComposeCb(action="edit")),
            cb_button(i18n("bot-btn-cancel"), CancelCb()),
        ]
    ]
