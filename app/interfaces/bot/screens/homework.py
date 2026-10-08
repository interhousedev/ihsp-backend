"""The Upcoming homework list with a Done button per item (UF-BOT-03)."""

from collections.abc import Sequence

from app.interfaces.bot.keyboards import homework_list
from app.interfaces.bot.utilities.formatting import fmt_date
from app.interfaces.bot.utilities.html import escape, shorten
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

MAX_ITEMS = 10
TEXT_LIMIT = 200


def _line(lesson: LessonRef, i18n: I18nContext) -> str:
    due = lesson.homework_due_date or lesson.date
    head = i18n(
        "bot-homework-item", subject=escape(lesson.subject_name), due=fmt_date(due)
    )
    return f"{head}\n{escape(shorten(lesson.homework_text or '', TEXT_LIMIT))}"


def build_homework(
    lessons: Sequence[LessonRef], i18n: I18nContext, app_url: str
) -> RenderedMessage:
    """List the homework still to do, soonest due date first."""
    items = sorted(lessons, key=lambda lesson: lesson.homework_due_date or lesson.date)
    items = items[:MAX_ITEMS]
    lines = [f"<b>{i18n('bot-homework-title')}</b>"]
    if items:
        lines.extend(_line(lesson, i18n) for lesson in items)
    else:
        lines.append(i18n("bot-homework-empty"))
    return RenderedMessage(
        text_html="\n\n".join(lines),
        buttons=homework_list.get(i18n, items, app_url),
    )
