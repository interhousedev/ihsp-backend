"""Marks of the last 7 days and the current semester results (UF-BOT-03)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.interfaces.bot.keyboards import marks as marks_keyboard
from app.interfaces.bot.utilities.formatting import MARK_TYPE_KEYS, fmt_date, number
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.academic import MarkRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

MAX_MARKS = 20


@dataclass(frozen=True, slots=True)
class SubjectResult:
    """A subject's semester mark."""

    name: str
    semester_mark: float | None


@dataclass(frozen=True, slots=True)
class MarksState:
    """Recent marks plus the semester results."""

    marks: tuple[MarkRef, ...]
    gpa: float | None
    subjects: tuple[SubjectResult, ...]


def parse_marks_state(marks: Sequence[MarkRef], results: dict[str, Any]) -> MarksState:
    """Combine ``MarksQueries.marks`` and ``MarksQueries.results`` outputs."""
    subjects = tuple(
        SubjectResult(name=str(item["name"]), semester_mark=item.get("semester_mark"))
        for item in results.get("subjects", [])
    )
    return MarksState(marks=tuple(marks), gpa=results.get("gpa"), subjects=subjects)


def _mark_line(mark: MarkRef, i18n: I18nContext) -> str:
    kind = i18n(MARK_TYPE_KEYS.get(mark.type, "bot-mark-type-lesson"))
    subject = escape(mark.subject_name)
    return f"{subject} — <b>{mark.value}</b> ({kind}), {fmt_date(mark.date)}"


def build_marks(
    state: MarksState, i18n: I18nContext, grades_url: str
) -> RenderedMessage:
    """Return the marks screen with an Open grades button."""
    lines = [f"<b>{i18n('bot-marks-recent')}</b>"]
    recent = sorted(state.marks, key=lambda mark: mark.date, reverse=True)[:MAX_MARKS]
    if recent:
        lines.extend(_mark_line(mark, i18n) for mark in recent)
    else:
        lines.append(i18n("bot-marks-none"))
    lines.append("")
    lines.append(f"<b>{i18n('bot-marks-semester')}</b>")
    lines.append(i18n("bot-marks-gpa", gpa=number(state.gpa)))
    lines.extend(
        f"{escape(subject.name)}: {number(subject.semester_mark)}"
        for subject in state.subjects
    )
    return RenderedMessage(
        text_html="\n".join(lines), buttons=marks_keyboard.get(i18n, grades_url)
    )
