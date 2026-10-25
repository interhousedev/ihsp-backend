"""The teacher's current or next lesson with its actions (UF-BOT-03)."""

from collections.abc import Sequence
from datetime import datetime

from app.interfaces.bot.keyboards import back_to_menu, current_lesson
from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.formatting import fmt_date, groups_label, time_range
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def pick_lesson(lessons: Sequence[LessonRef], now: datetime) -> LessonRef | None:
    """Return the running lesson, else the next one (cancelled ones are skipped)."""
    unfinished = [
        lesson
        for lesson in lessons
        if lesson.status == "scheduled" and lesson.ends_at > now
    ]
    return min(unfinished, key=lambda lesson: lesson.starts_at, default=None)


def build_current_lesson(
    lesson: LessonRef | None, now: datetime, i18n: I18nContext, urls: BotUrls
) -> RenderedMessage:
    """Return the lesson card, or a note when the teacher has none soon."""
    if lesson is None:
        return RenderedMessage(
            text_html=i18n("bot-lesson-none"), buttons=back_to_menu.get(i18n)
        )
    running = lesson.starts_at <= now
    title = i18n("bot-lesson-current" if running else "bot-lesson-next")
    lines = [
        f"<b>{title}</b>",
        f"{fmt_date(lesson.date)} {time_range(lesson)}",
        f"<b>{escape(lesson.subject_name)}</b> · {escape(groups_label(lesson))}",
    ]
    if lesson.room_name:
        lines.append(escape(lesson.room_name))
    return RenderedMessage(
        text_html="\n".join(lines),
        buttons=current_lesson.get(i18n, lesson.id, urls.staff_lesson(lesson.id)),
    )
