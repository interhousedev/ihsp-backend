"""Buttons under an email: Reply, Forward, Show full and Spam (MAIL-2)."""

from uuid import UUID

from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import MailCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64


def get(i18n: I18nContext, mail_id: UUID, *, truncated: bool) -> Rows:
    """Return the email buttons; Show full only when the body was cut."""
    mail = uuid_to_b64(mail_id)
    rows: Rows = [
        [
            cb_button(i18n("bot-btn-reply"), MailCb(mail=mail, action="reply")),
            cb_button(i18n("bot-btn-forward"), MailCb(mail=mail, action="fwd")),
        ]
    ]
    last = [cb_button(i18n("bot-btn-spam"), MailCb(mail=mail, action="spam"))]
    if truncated:
        last.insert(
            0, cb_button(i18n("bot-btn-full"), MailCb(mail=mail, action="full"))
        )
    rows.append(last)
    return rows
