"""Subject filter of mark notifications: one toggle per subject (BOT-13)."""

from collections.abc import Sequence

from app.interfaces.bot.keyboards.settings_main import open_cb
from app.interfaces.bot.utilities.html import shorten
from app.interfaces.bot.utilities.markup import Rows, cb_button, toggle_text
from app.shared.contracts.callbacks import SettingsCb
from app.shared.i18n.core import I18nContext

MAX_SUBJECTS = 40
NAME_LIMIT = 40


def get(i18n: I18nContext, names: Sequence[str], selected: Sequence[bool]) -> Rows:
    """Return a toggle per subject (by position) and Back."""
    rows: Rows = [
        [
            cb_button(
                toggle_text(shorten(name, NAME_LIMIT), chosen),
                SettingsCb(key="subject", value=str(index)),
            )
        ]
        for index, (name, chosen) in enumerate(zip(names, selected, strict=True))
        if index < MAX_SUBJECTS
    ]
    rows.append([cb_button(i18n("bot-btn-back"), open_cb("marks"))])
    return rows
