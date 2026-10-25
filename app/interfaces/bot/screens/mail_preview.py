"""Preview of an email the student is about to send (UF-MAIL-03, UF-MAIL-04)."""

from dataclasses import dataclass
from typing import Any

from app.interfaces.bot.keyboards import mail_preview
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

PREVIEW_KEYS = {
    "new": "bot-mail-preview-new",
    "reply": "bot-mail-preview-reply",
    "forward": "bot-mail-preview-forward",
}


@dataclass(frozen=True, slots=True)
class MailDraft:
    """A draft kept in the FSM while the student fills it in."""

    flow: str  # new, reply or forward
    to: tuple[str, ...] = ()
    subject: str = ""
    body_html: str = ""
    mail: str = ""  # packed id of the email being answered or forwarded

    def to_data(self) -> dict[str, Any]:
        """Return the JSON-safe form for FSM storage."""
        return {
            "flow": self.flow,
            "to": list(self.to),
            "subject": self.subject,
            "body_html": self.body_html,
            "mail": self.mail,
        }

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "MailDraft":
        """Rebuild the draft from FSM data."""
        return cls(
            flow=str(data.get("flow", "new")),
            to=tuple(data.get("to", ())),
            subject=str(data.get("subject", "")),
            body_html=str(data.get("body_html", "")),
            mail=str(data.get("mail", "")),
        )


def build_mail_preview(draft: MailDraft, i18n: I18nContext) -> RenderedMessage:
    """Show the draft with Send, Edit and Cancel."""
    body = draft.body_html or i18n("bot-mail-no-note")
    text = i18n(
        PREVIEW_KEYS[draft.flow],
        to=escape(", ".join(draft.to)),
        subject=escape(draft.subject),
        body=body,
    )
    return RenderedMessage(text_html=text, buttons=mail_preview.get(i18n))
