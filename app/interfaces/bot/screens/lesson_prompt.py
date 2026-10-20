"""The end-of-lesson prompt: attendance checklist and the homework step (BOT-16..19)."""

from datetime import datetime
from typing import Literal

from app.interfaces.bot.keyboards import (
    attendance_checklist,
    attendance_summary,
    lesson_journal,
)
from app.interfaces.bot.prompt_state import PromptState
from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.formatting import groups_label
from app.interfaces.bot.utilities.html import escape, shorten
from app.interfaces.bot.utilities.markup import Rows, web_app_button
from app.interfaces.bot.work_off_choice import WorkOffChoice
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext

# auto: checklist until attendance is submitted, then the summary.
# edit: always the checklist. closed: the summary without buttons.
PromptMode = Literal["auto", "edit", "closed"]

HOMEWORK_PREVIEW = 300


def _title(state: PromptState) -> str:
    lesson = state.lesson
    parts = [groups_label(lesson), lesson.subject_name]
    return escape(" · ".join(part for part in parts if part))


def _topic_line(state: PromptState, i18n: I18nContext) -> list[str]:
    if not state.lesson.topic:
        return []
    return [i18n("bot-prompt-topic", topic=escape(state.lesson.topic))]


def _checklist(
    state: PromptState,
    i18n: I18nContext,
    now: datetime,
    urls: BotUrls,
    work_off: WorkOffChoice | None,
) -> tuple[list[str], Rows]:
    minutes = state.minutes_left(now)
    key = "bot-prompt-ends-in" if minutes > 0 else "bot-prompt-ended"
    lines = [f"<b>{i18n(key, title=_title(state), minutes=minutes)}</b>"]
    lines.extend(_topic_line(state, i18n))
    lines.append(i18n("bot-prompt-hint", absent=state.absent_count))
    if work_off is not None:
        lines.append(i18n("bot-prompt-work-off", task=escape(work_off.summary(i18n))))
    rows = attendance_checklist.get(i18n, state.lesson.id, state.roster)
    rows.extend(lesson_journal.open_button(i18n, state.lesson.id))
    hidden = len(state.roster) - attendance_checklist.MAX_ROSTER_BUTTONS
    if hidden > 0:
        lines.append(i18n("bot-prompt-roster-cut", count=hidden))
        rows.append(
            [
                web_app_button(
                    i18n("bot-btn-open-lesson"), urls.staff_lesson(state.lesson.id)
                )
            ]
        )
    return lines, rows


def _summary(
    state: PromptState, i18n: I18nContext, *, closed: bool
) -> tuple[list[str], Rows]:
    lines = [f"<b>{_title(state)}</b>"]
    if state.absent_count:
        lines.append(i18n("bot-prompt-absent", count=state.absent_count))
    else:
        lines.append(i18n("bot-prompt-all-present"))
    lines.extend(_topic_line(state, i18n))
    if state.homework_text:
        text = escape(shorten(state.homework_text, HOMEWORK_PREVIEW))
        lines.append(i18n("bot-prompt-homework", text=text))
    else:
        lines.append(
            i18n("bot-prompt-no-homework" if closed else "bot-prompt-ask-homework")
        )
    rows = (
        []
        if closed
        else attendance_summary.get(
            i18n, state.lesson.id, has_homework=bool(state.homework_text)
        )
        + lesson_journal.open_button(i18n, state.lesson.id)
    )
    return lines, rows


def build_lesson_prompt(
    state: PromptState,
    i18n: I18nContext,
    *,
    now: datetime,
    urls: BotUrls,
    mode: PromptMode = "auto",
    note: str | None = None,
    work_off: WorkOffChoice | None = None,
) -> RenderedMessage:
    """Build the prompt for the lesson from the server's state."""
    show_summary = mode == "closed" or (mode == "auto" and state.attendance_submitted)
    if show_summary:
        lines, rows = _summary(state, i18n, closed=mode == "closed")
    else:
        lines, rows = _checklist(state, i18n, now, urls, work_off)
    if note:
        lines.insert(1, f"<i>{escape(note)}</i>")
    return RenderedMessage(text_html="\n".join(lines), buttons=rows or None)
