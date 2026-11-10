"""Keyboard of the Marks screen: pager, Open grades, Back and Menu."""

from typing import Any

from app.interfaces.bot.utilities.markup import Rows, web_app_button
from app.interfaces.bot.utilities.navigation import nav_rows
from app.interfaces.bot.utilities.pagination import Page, pager_row
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext, grades_url: str, page: Page[Any]) -> Rows:
    """Return the pager, the Open grades row and the navigation footer."""
    rows: Rows = []
    pager = pager_row("mk", page)
    if pager:
        rows.append(pager)
    rows.append([web_app_button(i18n("bot-btn-open-grades"), grades_url)])
    return [*rows, *nav_rows(i18n)]
