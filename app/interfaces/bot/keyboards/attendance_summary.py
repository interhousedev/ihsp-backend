"""Keyboard of the submitted-attendance message: edit it, then the homework step."""

from uuid import UUID

from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import AttActionCb, HomeworkPromptCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64


def get(i18n: I18nContext, lesson_id: UUID, *, has_homework: bool) -> Rows:
    """Return Edit attendance, the homework buttons and Set topic."""
    lesson = uuid_to_b64(lesson_id)
    rows: Rows = [
        [
            cb_button(
                i18n("bot-btn-edit-attendance"),
                AttActionCb(lesson=lesson, action="edit"),
            )
        ]
    ]
    add = cb_button(
        i18n("bot-btn-edit-homework" if has_homework else "bot-btn-add-homework"),
        HomeworkPromptCb(lesson=lesson, action="add"),
    )
    if has_homework:
        rows.append([add])
    else:
        no_homework = cb_button(
            i18n("bot-btn-no-homework"), HomeworkPromptCb(lesson=lesson, action="none")
        )
        rows.append([add, no_homework])
    rows.append(
        [
            cb_button(
                i18n("bot-btn-topic"), HomeworkPromptCb(lesson=lesson, action="topic")
            )
        ]
    )
    return rows
