"""Preview of the homework text the teacher sent (BOT-18)."""

from uuid import UUID

from app.interfaces.bot.keyboards import homework_preview
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_homework_preview(
    lesson_id: UUID, text: str, i18n: I18nContext
) -> RenderedMessage:
    """Show the text with Save, Edit and Cancel."""
    return RenderedMessage(
        text_html=i18n("bot-homework-preview", text=escape(text)),
        buttons=homework_preview.get(i18n, lesson_id),
    )
