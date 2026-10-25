"""Today for a teacher: lessons with audience and attendance state (UF-BOT-03)."""

from collections.abc import Collection, Sequence
from datetime import date, datetime
from uuid import UUID

from app.interfaces.bot.keyboards import today_teacher
from app.interfaces.bot.utilities.formatting import fmt_date, groups_label, time_range
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def _attendance_mark(
    lesson: LessonRef, missing: Collection[UUID], now: datetime, i18n: I18nContext
) -> str:
    if lesson.status == "cancelled" or lesson.ends_at > now:
        return ""
    key = (
        "bot-today-attendance-missing"
        if lesson.id in missing
        else "bot-today-attendance-done"
    )
    return f" · {i18n(key)}"


def _line(
    lesson: LessonRef, missing: Collection[UUID], now: datetime, i18n: I18nContext
) -> str:
    parts = [f"{time_range(lesson)} <b>{escape(lesson.subject_name)}</b>"]
    if lesson.group_names:
        parts.append(escape(groups_label(lesson)))
    if lesson.room_name:
        parts.append(escape(lesson.room_name))
    text = " · ".join(parts)
    if lesson.status == "cancelled":
        return f"<s>{text}</s> {i18n('bot-lesson-cancelled')}"
    return text + _attendance_mark(lesson, missing, now, i18n)


def build_today_teacher(
    lessons: Sequence[LessonRef],
    missing_attendance: Collection[UUID],
    today: date,
    now: datetime,
    i18n: I18nContext,
) -> RenderedMessage:
    """List the teacher's lessons; finished ones show whether attendance is done."""
    lines = [f"<b>{i18n('bot-today-title', date=fmt_date(today))}</b>"]
    if lessons:
        ordered = sorted(lessons, key=lambda lesson: lesson.starts_at)
        lines.extend(_line(lesson, missing_attendance, now, i18n) for lesson in ordered)
    else:
        lines.append(i18n("bot-today-empty"))
    return RenderedMessage(text_html="\n".join(lines), buttons=today_teacher.get(i18n))
