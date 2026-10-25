"""Material / Attachment choice for a lesson that is already known."""

from uuid import UUID

from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import CancelCb, ResourceLessonCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64


def get(i18n: I18nContext, lesson_id: UUID) -> Rows:
    """Return Material, Attachment and Cancel."""
    encoded = uuid_to_b64(lesson_id)
    return [
        [
            cb_button(
                i18n("bot-btn-material"), ResourceLessonCb(lesson=encoded, role="m")
            ),
            cb_button(
                i18n("bot-btn-attachment"), ResourceLessonCb(lesson=encoded, role="a")
            ),
        ],
        [cb_button(i18n("bot-btn-cancel"), CancelCb())],
    ]
