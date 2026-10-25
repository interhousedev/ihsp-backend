"""Undo button shown after an email was marked as spam."""

from uuid import UUID

from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import MailCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64


def get(i18n: I18nContext, mail_id: UUID) -> Rows:
    """Return the Undo row."""
    return [
        [
            cb_button(
                i18n("bot-btn-undo"),
                MailCb(mail=uuid_to_b64(mail_id), action="unspam"),
            )
        ]
    ]
