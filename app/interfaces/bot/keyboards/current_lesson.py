"""Keyboard of the Current lesson screen (UF-BOT-03)."""

from uuid import UUID

from app.interfaces.bot.utilities.markup import Rows, cb_button, web_app_button
from app.shared.contracts.callbacks import (
    AttActionCb,
    HomeworkPromptCb,
    MenuCb,
    ResourceLessonCb,
)
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64

START_RESOURCE = "p"  # ResourceLessonCb.role: start adding a resource to this lesson


def get(i18n: I18nContext, lesson_id: UUID, lesson_url: str) -> Rows:
    """Return Attendance, Homework, Add resource, Open lesson and Back."""
    lesson = uuid_to_b64(lesson_id)
    return [
        [
            cb_button(
                i18n("bot-btn-attendance"),
                AttActionCb(lesson=lesson, action="edit"),
            ),
            cb_button(
                i18n("bot-btn-homework"), HomeworkPromptCb(lesson=lesson, action="add")
            ),
        ],
        [
            cb_button(
                i18n("bot-btn-add-resource"),
                ResourceLessonCb(lesson=lesson, role=START_RESOURCE),
            )
        ],
        [web_app_button(i18n("bot-btn-open-lesson"), lesson_url)],
        [cb_button(i18n("bot-btn-back"), MenuCb(screen="menu"))],
    ]
