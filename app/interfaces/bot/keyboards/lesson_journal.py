"""Lesson journal: students with their temporary marks, then the mark buttons."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from app.interfaces.bot.callbacks import JournalCb, JournalMarkCb, JournalStudentCb
from app.interfaces.bot.keyboards.attendance_checklist import (
    MAX_ROSTER_BUTTONS,
    NAME_LIMIT,
)
from app.interfaces.bot.prompt_state import RosterItem
from app.interfaces.bot.utilities.markup import Rows, cb_button, pairs
from app.modules.academic.domain.classwork.temporary_mark import MARK_SCALE
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64

REMOVE_VALUE = 0


def _label(item: RosterItem, mark: int | None) -> str:
    name = item.name if len(item.name) <= NAME_LIMIT else item.name[:NAME_LIMIT] + "…"
    return name if mark is None else f"{name} · {mark}"


def open_button(i18n: I18nContext, lesson_id: UUID) -> Rows:
    """The Journal row of the lesson prompt."""
    lesson = uuid_to_b64(lesson_id)
    return [
        [cb_button(i18n("bot-btn-journal"), JournalCb(lesson=lesson, action="open"))]
    ]


def students(
    i18n: I18nContext,
    lesson_id: UUID,
    roster: Sequence[RosterItem],
    marks: Mapping[UUID, int],
) -> Rows:
    """One button per student with the current mark, then Back."""
    lesson = uuid_to_b64(lesson_id)
    buttons = [
        cb_button(
            _label(item, marks.get(item.user_id)),
            JournalStudentCb(lesson=lesson, pos=item.position),
        )
        for item in roster[:MAX_ROSTER_BUTTONS]
    ]
    rows = pairs(buttons)
    rows.append(
        [cb_button(i18n("bot-btn-back"), JournalCb(lesson=lesson, action="back"))]
    )
    return rows


def marks_for(
    i18n: I18nContext, lesson_id: UUID, position: int, *, has_mark: bool
) -> Rows:
    """The mark scale, Remove when there is a mark, and Back to the list."""
    lesson = uuid_to_b64(lesson_id)
    rows: Rows = [
        [
            cb_button(
                str(value), JournalMarkCb(lesson=lesson, pos=position, value=value)
            )
            for value in MARK_SCALE
        ]
    ]
    if has_mark:
        remove = JournalMarkCb(lesson=lesson, pos=position, value=REMOVE_VALUE)
        rows.append([cb_button(i18n("bot-btn-journal-remove"), remove)])
    rows.append(
        [cb_button(i18n("bot-btn-back"), JournalCb(lesson=lesson, action="open"))]
    )
    return rows
