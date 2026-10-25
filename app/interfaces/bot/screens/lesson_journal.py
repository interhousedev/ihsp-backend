"""The lesson journal screens: the student list and one student's marks."""

from collections.abc import Mapping
from uuid import UUID

from app.interfaces.bot.keyboards import lesson_journal
from app.interfaces.bot.prompt_state import PromptState, RosterItem
from app.interfaces.bot.utilities.formatting import groups_label
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def _title(state: PromptState) -> str:
    lesson = state.lesson
    parts = [groups_label(lesson), lesson.subject_name]
    return escape(" · ".join(part for part in parts if part))


def build_journal(
    state: PromptState, marks: Mapping[UUID, int], i18n: I18nContext
) -> RenderedMessage:
    """The lesson's students, each with the temporary mark when there is one."""
    lines = [
        f"<b>{i18n('bot-journal-title', title=_title(state))}</b>",
        i18n("bot-journal-hint"),
    ]
    rows = lesson_journal.students(i18n, state.lesson.id, state.roster, marks)
    return RenderedMessage(text_html="\n".join(lines), buttons=rows)


def build_journal_student(
    state: PromptState, item: RosterItem, mark: int | None, i18n: I18nContext
) -> RenderedMessage:
    """One student's current mark and the mark buttons."""
    name = escape(item.name)
    if mark is None:
        text = i18n("bot-journal-student-none", name=name)
    else:
        text = i18n("bot-journal-student", name=name, mark=mark)
    rows = lesson_journal.marks_for(
        i18n, state.lesson.id, item.position, has_mark=mark is not None
    )
    return RenderedMessage(text_html=f"<b>{_title(state)}</b>\n{text}", buttons=rows)
