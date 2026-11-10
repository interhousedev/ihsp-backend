"""Footer of first-level screens: ← Back and ⌂ Menu, both to the hub."""

from app.interfaces.bot.utilities.markup import Rows
from app.interfaces.bot.utilities.navigation import nav_rows
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext) -> Rows:
    """Return the Back and Menu row."""
    return nav_rows(i18n)
