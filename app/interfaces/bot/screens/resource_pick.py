"""Ask where a file or link goes: a lesson, then Material or Attachment (BOT-20)."""

from collections.abc import Sequence

from app.interfaces.bot.keyboards import cancel, resource_lessons, resource_roles
from app.interfaces.bot.utilities.formatting import lesson_label
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_resource_ask(i18n: I18nContext) -> RenderedMessage:
    """Ask the teacher to send a file or a link (from Current lesson)."""
    return RenderedMessage(text_html=i18n("bot-resource-ask"), buttons=cancel.get(i18n))


def build_resource_pick(
    lessons: Sequence[LessonRef], i18n: I18nContext
) -> RenderedMessage:
    """Offer today's and upcoming lessons; no lessons means nothing to attach to."""
    if not lessons:
        return RenderedMessage(
            text_html=i18n("bot-resource-no-lessons"), buttons=cancel.get(i18n)
        )
    return RenderedMessage(
        text_html=i18n("bot-resource-pick"),
        buttons=resource_lessons.get(i18n, lessons),
    )


def build_resource_roles(lesson: LessonRef, i18n: I18nContext) -> RenderedMessage:
    """Offer Material or Attachment for a lesson that is already chosen."""
    return RenderedMessage(
        text_html=i18n("bot-resource-role", lesson=lesson_label(lesson)),
        buttons=resource_roles.get(i18n, lesson.id),
    )
