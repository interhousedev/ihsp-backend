"""Keyboard under the homework preview: Save, Edit, Cancel (BOT-18)."""

from uuid import UUID

from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import HomeworkPromptCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64


def get(i18n: I18nContext, lesson_id: UUID) -> Rows:
    """Return the preview buttons for the lesson."""
    lesson = uuid_to_b64(lesson_id)
    return [
        [
            cb_button(
                i18n("bot-btn-save"), HomeworkPromptCb(lesson=lesson, action="save")
            ),
            cb_button(
                i18n("bot-btn-edit"), HomeworkPromptCb(lesson=lesson, action="edit")
            ),
            cb_button(
                i18n("bot-btn-cancel"),
                HomeworkPromptCb(lesson=lesson, action="cancel"),
            ),
        ]
    ]
