"""Lesson picker for a file or link the teacher sent (BOT-20)."""

from collections.abc import Sequence

from app.interfaces.bot.utilities.formatting import lesson_label
from app.interfaces.bot.utilities.markup import Rows, cb_button, none_button
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.callbacks import CancelCb, ResourceLessonCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64

MAX_LESSONS = 8


def get(i18n: I18nContext, lessons: Sequence[LessonRef]) -> Rows:
    """Return a heading and Material / Attachment buttons per lesson, then Cancel."""
    rows: Rows = []
    for lesson in lessons[:MAX_LESSONS]:
        encoded = uuid_to_b64(lesson.id)
        rows.append([none_button(lesson_label(lesson))])
        rows.append(
            [
                cb_button(
                    i18n("bot-btn-material"), ResourceLessonCb(lesson=encoded, role="m")
                ),
                cb_button(
                    i18n("bot-btn-attachment"),
                    ResourceLessonCb(lesson=encoded, role="a"),
                ),
            ]
        )
    rows.append([cb_button(i18n("bot-btn-cancel"), CancelCb())])
    return rows
