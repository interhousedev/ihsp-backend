"""The mail list: one button per email, New email and paging (MAIL-3)."""

from collections.abc import Sequence

from app.interfaces.bot.callbacks import MailComposeCb
from app.interfaces.bot.utilities.formatting import fmt_date
from app.interfaces.bot.utilities.html import shorten
from app.interfaces.bot.utilities.markup import Button, Rows, cb_button
from app.shared.contracts.callbacks import MailCb, MailListCb, MenuCb
from app.shared.contracts.mail import MailSummary
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64

LABEL_LIMIT = 58


def _label(mail: MailSummary) -> str:
    sender = mail.from_address.split("@")[0] if mail.direction == "in" else "→"
    return shorten(
        f"{fmt_date(mail.occurred_at)} {sender}: {mail.subject}", LABEL_LIMIT
    )


def get(
    i18n: I18nContext,
    mails: Sequence[MailSummary],
    *,
    older_before: int | None,
    is_first_page: bool,
) -> Rows:
    """Return one row per email, then New email, Older / Newest and Back."""
    rows: Rows = [
        [cb_button(_label(mail), MailCb(mail=uuid_to_b64(mail.id), action="open"))]
        for mail in mails
    ]
    rows.append([cb_button(i18n("bot-btn-new-mail"), MailComposeCb(action="new"))])
    paging: list[Button] = []
    if not is_first_page:
        paging.append(cb_button(i18n("bot-btn-newest"), MailListCb(before=0)))
    if older_before is not None:
        paging.append(cb_button(i18n("bot-btn-older"), MailListCb(before=older_before)))
    if paging:
        rows.append(paging)
    rows.append([cb_button(i18n("bot-btn-back"), MenuCb(screen="menu"))])
    return rows
