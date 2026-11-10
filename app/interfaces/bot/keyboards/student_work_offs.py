"""Keyboard of the student's work-off list: pager, Back and Menu."""

from typing import Any

from app.interfaces.bot.utilities.markup import Rows
from app.interfaces.bot.utilities.navigation import nav_rows
from app.interfaces.bot.utilities.pagination import Page, pager_row
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext, page: Page[Any]) -> Rows:
    """Return the pager and the navigation footer."""
    pager = pager_row("wo", page)
    return [*([pager] if pager else []), *nav_rows(i18n)]
