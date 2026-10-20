"""The student's open work-offs: date, lesson, teacher, task and due date (WO-5)."""

from collections.abc import Sequence
from datetime import date
from typing import Any

from app.interfaces.bot.keyboards import student_work_offs
from app.interfaces.bot.utilities.formatting import fmt_date
from app.interfaces.bot.utilities.html import escape, shorten
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

MAX_ITEMS = 10
TEXT_LIMIT = 300


def _item(raw: dict[str, Any], i18n: I18nContext) -> str:
    lines = [
        i18n(
            "bot-workoffs-student-item",
            date=fmt_date(date.fromisoformat(str(raw["date"]))),
            period=raw["period"],
            subject=escape(str(raw["subject_name"])),
        )
    ]
    if raw.get("teacher_name"):
        lines.append(
            i18n("bot-workoffs-student-teacher", teacher=escape(raw["teacher_name"]))
        )
    lines.append(escape(shorten(str(raw["text"]), TEXT_LIMIT)))
    if raw.get("due_date"):
        due = fmt_date(date.fromisoformat(str(raw["due_date"])))
        lines.append(i18n("bot-workoffs-student-due", due=due))
    return "\n".join(lines)


def build_student_work_offs(
    items: Sequence[dict[str, Any]], i18n: I18nContext
) -> RenderedMessage:
    """List the open work-offs, newest lesson first."""
    lines = [f"<b>{i18n('bot-workoffs-student-title')}</b>"]
    if not items:
        lines.append(i18n("bot-workoffs-student-empty"))
    lines.extend(_item(raw, i18n) for raw in items[:MAX_ITEMS])
    if len(items) > MAX_ITEMS:
        lines.append(i18n("bot-workoffs-student-more", count=len(items) - MAX_ITEMS))
    return RenderedMessage(
        text_html="\n\n".join(lines), buttons=student_work_offs.get(i18n)
    )
