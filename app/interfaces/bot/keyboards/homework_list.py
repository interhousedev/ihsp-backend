"""Homework list: a Done button per item, Open homework and Back (UF-BOT-03)."""

from app.interfaces.bot.utilities.formatting import fmt_date
from app.interfaces.bot.utilities.html import shorten
from app.interfaces.bot.utilities.markup import Rows, cb_button, web_app_button
from app.interfaces.bot.utilities.navigation import nav_rows
from app.interfaces.bot.utilities.pagination import Page, pager_row
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.callbacks import HomeworkDoneCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64

LABEL_LIMIT = 40


def get(i18n: I18nContext, page: Page[LessonRef], app_url: str) -> Rows:
    """Return a button per item that ticks it, pager, Open homework, Back and Menu."""
    rows: Rows = [
        [
            cb_button(
                f"✓ {shorten(lesson.subject_name, LABEL_LIMIT)}"
                f" · {fmt_date(lesson.date)}",
                HomeworkDoneCb(lesson=uuid_to_b64(lesson.id), done=True),
            )
        ]
        for lesson in page.items
    ]
    pager = pager_row("hw", page)
    if pager:
        rows.append(pager)
    rows.append([web_app_button(i18n("bot-btn-open-homework"), app_url)])
    rows.extend(nav_rows(i18n))
    return rows
