"""An email as a Telegram message with its action buttons (MAIL-2)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.interfaces.bot.keyboards import mail_actions
from app.interfaces.bot.utilities.formatting import fmt_datetime
from app.interfaces.bot.utilities.html import escape, visible_length
from app.interfaces.bot.utilities.message_split import MAX_MESSAGE_LENGTH, truncate_html
from app.shared.contracts.files import FileRef
from app.shared.contracts.mail import MailSummary
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

# Room for the header, attachment list and the tags closed by the cut.
RESERVED = 600
TELEGRAM_FILE_LIMIT = 50 * 1000 * 1000


@dataclass(frozen=True, slots=True)
class MailView:
    """The result of ``MailApi.view``."""

    summary: MailSummary
    text: str
    html_telegram: str
    attachments: tuple[FileRef, ...]
    truncated: bool


def parse_mail_view(raw: dict[str, Any]) -> MailView:
    """Convert the dict returned by ``MailApi.view``."""
    return MailView(
        summary=raw["summary"],
        text=str(raw.get("text", "")),
        html_telegram=str(raw.get("html_telegram", "")),
        attachments=tuple(raw.get("attachments", ())),
        truncated=bool(raw.get("truncated", False)),
    )


def _body(view: MailView, i18n: I18nContext) -> str:
    if view.summary.purged:
        return f"<i>{i18n('bot-mail-purged')}</i>\n{escape(view.summary.snippet)}"
    return view.html_telegram or escape(view.text)


def _header(summary: MailSummary, i18n: I18nContext) -> str:
    lines = [
        f"<b>{escape(summary.subject or i18n('bot-mail-no-subject'))}</b>",
        i18n("bot-mail-from", sender=escape(summary.from_address)),
        fmt_datetime(summary.occurred_at),
    ]
    return "\n".join(lines)


def _attachment_lines(
    listed: Sequence[str], skipped: Sequence[str], i18n: I18nContext
) -> list[str]:
    lines = [f"📎 {escape(name)}" for name in listed]
    lines.extend(
        i18n("bot-mail-attachment-skipped", name=escape(name)) for name in skipped
    )
    return lines


def build_mail_message(
    view: MailView,
    i18n: I18nContext,
    *,
    documents: tuple[tuple[str, bytes], ...] = (),
    listed_names: Sequence[str] = (),
    skipped_names: Sequence[str] = (),
) -> RenderedMessage:
    """Build the email message.

    ``documents`` are attachments sent along as files; ``listed_names`` are shown
    by name only (the list view); ``skipped_names`` did not pass the size rule or
    the file checks.
    """
    header = _header(view.summary, i18n)
    extra = _attachment_lines(listed_names, skipped_names, i18n)
    budget = max(200, MAX_MESSAGE_LENGTH - RESERVED - visible_length(header))
    body, cut = truncate_html(_body(view, i18n), budget)
    parts = [header, "", body, *(["", *extra] if extra else [])]
    truncated = (view.truncated or cut) and not view.summary.purged
    return RenderedMessage(
        text_html="\n".join(parts),
        buttons=mail_actions.get(i18n, view.summary.id, truncated=truncated),
        documents=documents,
    )
