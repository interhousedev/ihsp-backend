"""Messages for a prompt that can no longer be used: expired or reassigned."""

from uuid import UUID

from app.interfaces.bot.keyboards import open_lesson
from app.interfaces.bot.urls import BotUrls
from app.shared.base_error import ForbiddenError
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def is_window_closed(error: ForbiddenError) -> bool:
    """True when the edit window of the lesson is over (not a reassignment)."""
    return "window" in error.code or "expired" in error.code


def build_prompt_expired(
    lesson_id: UUID, i18n: I18nContext, urls: BotUrls
) -> RenderedMessage:
    """Tell the teacher to continue in the staff portal (BOT-19)."""
    return RenderedMessage(
        text_html=i18n("bot-prompt-expired"),
        buttons=open_lesson.get(i18n, urls.staff_lesson(lesson_id)),
    )


def build_prompt_reassigned(i18n: I18nContext) -> RenderedMessage:
    """The teacher is no longer the lesson's teacher."""
    return RenderedMessage(text_html=i18n("bot-prompt-reassigned"))
