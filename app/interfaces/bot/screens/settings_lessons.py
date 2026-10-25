"""Lesson settings screen: link lead time and the end-of-lesson prompt (STF-10)."""

from app.interfaces.bot.keyboards import settings_lessons
from app.shared.contracts.identity import UserPreferences, UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_settings_lessons(
    user: UserRef, prefs: UserPreferences, i18n: I18nContext
) -> RenderedMessage:
    """Return the lead time choices and, for teachers, the prompt toggle."""
    return RenderedMessage(
        text_html=i18n("bot-settings-lessons"),
        buttons=settings_lessons.get(i18n, prefs, user.roles),
    )
