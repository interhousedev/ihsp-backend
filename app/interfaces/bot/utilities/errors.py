"""One look for every error the bot shows: bold title, the cause, muted error ID."""

from app.interfaces.bot.utilities.html import escape
from app.shared.i18n.core import I18nContext


def error_text(i18n: I18nContext, body: str, error_id: str) -> str:
    """Plain text of the error (for callback alerts)."""
    return f"{body}\n\n{i18n.get('bot-error-id', error_id=error_id)}"


def error_html(i18n: I18nContext, body: str, error_id: str) -> str:
    """HTML of the error for a chat message."""
    return "\n\n".join(
        [
            f"<b>{escape(i18n.get('bot-error-title'))}</b>",
            escape(body),
            f"<i>{escape(i18n.get('bot-error-id', error_id=error_id))}</i>",
        ]
    )
