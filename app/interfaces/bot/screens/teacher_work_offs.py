"""The teacher's open work-offs: tap one to mark it done (WO-7)."""

from collections.abc import Sequence
from math import ceil
from typing import Any

from app.interfaces.bot.keyboards import teacher_work_offs
from app.interfaces.bot.utilities.html import escape
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def clamp_page(page: int, total: int) -> int:
    """Return a page that exists (the list shrinks as items are done)."""
    pages = max(1, ceil(total / teacher_work_offs.PAGE_SIZE))
    return min(max(page, 0), pages - 1)


def build_teacher_work_offs(
    items: Sequence[dict[str, Any]],
    i18n: I18nContext,
    *,
    page: int,
    undo: str | None = None,
    note: str | None = None,
) -> RenderedMessage:
    """List a page of open work-offs; ``undo`` is the id (b64) of the last done."""
    size = teacher_work_offs.PAGE_SIZE
    page = clamp_page(page, len(items))
    pages = max(1, ceil(len(items) / size))
    lines = [f"<b>{i18n('bot-workoffs-teacher-title', count=len(items))}</b>"]
    if note:
        lines.append(escape(note))
    lines.append(
        i18n("bot-workoffs-teacher-hint" if items else "bot-workoffs-teacher-empty")
    )
    rows = teacher_work_offs.get(
        i18n, items[page * size : (page + 1) * size], page=page, pages=pages, undo=undo
    )
    return RenderedMessage(text_html="\n".join(lines), buttons=rows)
