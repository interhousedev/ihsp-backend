"""Homework list: a Done button per item, Open homework and Back (UF-BOT-03)."""

from collections.abc import Sequence

from app.interfaces.bot.utilities.formatting import fmt_date
from app.interfaces.bot.utilities.html import shorten
from app.interfaces.bot.utilities.markup import Rows, cb_button, web_app_button
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.callbacks import HomeworkDoneCb, MenuCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64

LABEL_LIMIT = 40


def get(i18n: I18nContext, lessons: Sequence[LessonRef], app_url: str) -> Rows:
    """Return a button per item that ticks it, then Open homework and Back."""
    rows: Rows = [
        [
            cb_button(
                f"✓ {shorten(lesson.subject_name, LABEL_LIMIT)}"
                f" · {fmt_date(lesson.date)}",
                HomeworkDoneCb(lesson=uuid_to_b64(lesson.id), done=True),
            )
        ]
        for lesson in lessons
    ]
    rows.append([web_app_button(i18n("bot-btn-open-homework"), app_url)])
    rows.append([cb_button(i18n("bot-btn-back"), MenuCb(screen="menu"))])
    return rows
