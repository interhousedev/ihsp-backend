"""The mailbox list: the last 10 emails as buttons (MAIL-3)."""

from collections.abc import Sequence

from app.interfaces.bot.keyboards import mail_list
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.mail import MailSummary
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

PAGE_SIZE = 10


def build_mail_list(
    mails: Sequence[MailSummary],
    address: str,
    i18n: I18nContext,
    *,
    is_first_page: bool,
) -> RenderedMessage:
    """Return the list with New email and paging buttons."""
    lines = [i18n("bot-mail-title", address=escape(address))]
    if not mails:
        lines.append(i18n("bot-mail-empty"))
    older = int(mails[-1].occurred_at.timestamp()) if len(mails) >= PAGE_SIZE else None
    return RenderedMessage(
        text_html="\n".join(lines),
        buttons=mail_list.get(
            i18n, mails, older_before=older, is_first_page=is_first_page
        ),
    )
