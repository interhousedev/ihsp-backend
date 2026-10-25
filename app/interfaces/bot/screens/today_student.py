"""Today for a student: lessons with times and rooms (UF-BOT-03)."""

from collections.abc import Sequence
from datetime import date

from app.interfaces.bot.keyboards import back_to_menu
from app.interfaces.bot.utilities.formatting import fmt_date, time_range
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def _line(lesson: LessonRef, i18n: I18nContext) -> str:
    text = f"{time_range(lesson)} <b>{escape(lesson.subject_name)}</b>"
    if lesson.room_name:
        text += f" · {escape(lesson.room_name)}"
    if lesson.status == "cancelled":
        return f"<s>{text}</s> {i18n('bot-lesson-cancelled')}"
    return text


def build_today_student(
    lessons: Sequence[LessonRef], today: date, i18n: I18nContext
) -> RenderedMessage:
    """List today's lessons in time order."""
    lines = [f"<b>{i18n('bot-today-title', date=fmt_date(today))}</b>"]
    if lessons:
        ordered = sorted(lessons, key=lambda lesson: (lesson.starts_at, lesson.period))
        lines.extend(_line(lesson, i18n) for lesson in ordered)
    else:
        lines.append(i18n("bot-today-empty"))
    return RenderedMessage(text_html="\n".join(lines), buttons=back_to_menu.get(i18n))
