"""Template list of the work-off step: one button per template and None."""

from uuid import UUID

from app.interfaces.bot.callbacks import WorkOffPickCb
from app.interfaces.bot.utilities.html import shorten
from app.interfaces.bot.utilities.markup import Rows, cb_button, toggle_text
from app.interfaces.bot.work_off_choice import WorkOffChoice
from app.shared.contracts.callbacks import AttActionCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64

LABEL_LIMIT = 40


def get(i18n: I18nContext, lesson_id: UUID, choice: WorkOffChoice) -> Rows:
    """Return None, a button per template (by position) and Back to the checklist."""
    lesson = uuid_to_b64(lesson_id)
    nothing = not choice.chosen
    rows: Rows = [
        [
            cb_button(
                toggle_text(i18n("bot-btn-work-off-none"), nothing),
                WorkOffPickCb(lesson=lesson, pos=0),
            )
        ]
    ]
    for index, template in enumerate(choice.templates, start=1):
        selected = choice.template is not None and choice.template.id == template.id
        label = shorten(template.text.replace("\n", " "), LABEL_LIMIT)
        rows.append(
            [
                cb_button(
                    toggle_text(label, selected),
                    WorkOffPickCb(lesson=lesson, pos=index),
                )
            ]
        )
    rows.append(
        [cb_button(i18n("bot-btn-back"), AttActionCb(lesson=lesson, action="edit"))]
    )
    return rows
