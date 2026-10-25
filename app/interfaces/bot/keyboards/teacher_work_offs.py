"""Open work-offs of a teacher: one button per item, paging, Undo and Back (WO-7)."""

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from app.interfaces.bot.callbacks import WorkOffDoneCb, WorkOffPageCb, WorkOffUndoCb
from app.interfaces.bot.utilities.formatting import fmt_date
from app.interfaces.bot.utilities.html import shorten
from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import MenuCb
from app.shared.i18n.core import I18nContext
from app.shared.ids import uuid_to_b64

PAGE_SIZE = 8
LABEL_LIMIT = 56


def item_label(item: dict[str, Any]) -> str:
    """Return ``Student — group · DD.MM subject`` for one open work-off."""
    day = fmt_date(date.fromisoformat(str(item["date"])))
    text = (
        f"{item['student_name']} — {item['group_name']} · {day} {item['subject_name']}"
    )
    return shorten(text, LABEL_LIMIT)


def get(
    i18n: I18nContext,
    page_items: Sequence[dict[str, Any]],
    *,
    page: int,
    pages: int,
    undo: str | None,
) -> Rows:
    """Return the item buttons, the paging row, the Undo row and Back."""
    rows: Rows = [
        [
            cb_button(
                item_label(item),
                WorkOffDoneCb(item=uuid_to_b64(UUID(str(item["id"]))), page=page),
            )
        ]
        for item in page_items
    ]
    paging = []
    if page > 0:
        paging.append(cb_button("‹", WorkOffPageCb(page=page - 1)))
    if page + 1 < pages:
        paging.append(cb_button("›", WorkOffPageCb(page=page + 1)))
    if paging:
        rows.append(paging)
    if undo is not None:
        rows.append(
            [
                cb_button(
                    i18n("bot-btn-work-off-undo"), WorkOffUndoCb(item=undo, page=page)
                )
            ]
        )
    rows.append([cb_button(i18n("bot-btn-back"), MenuCb(screen="menu"))])
    return rows
