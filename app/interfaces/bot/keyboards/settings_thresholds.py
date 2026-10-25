"""Alert thresholds: GPA, semester mark and single mark, each off or a preset."""

from app.interfaces.bot.keyboards.settings_main import open_cb
from app.interfaces.bot.settings_patch import MARK_PRESETS, OFF, RATING_PRESETS
from app.interfaces.bot.utilities.markup import (
    Button,
    Rows,
    cb_button,
    none_button,
    toggle_text,
)
from app.shared.contracts.callbacks import SettingsCb
from app.shared.contracts.identity import UserPreferences
from app.shared.i18n.core import I18nContext


def _row(
    i18n: I18nContext, key: str, presets: tuple[str, ...], current: str
) -> list[Button]:
    values = (OFF, *presets)
    return [
        cb_button(
            toggle_text(
                i18n("bot-set-off") if value == OFF else value, value == current
            ),
            SettingsCb(key=key, value=value),
        )
        for value in values
    ]


def get(i18n: I18nContext, prefs: UserPreferences) -> Rows:
    """Return the three threshold rows with the current choice checked."""
    gpa = OFF if prefs.alerts_gpa_below is None else f"{prefs.alerts_gpa_below:.1f}"
    semester = (
        OFF
        if prefs.alerts_semester_mark_below is None
        else f"{prefs.alerts_semester_mark_below:.1f}"
    )
    mark = OFF if prefs.alerts_mark_below is None else str(prefs.alerts_mark_below)
    return [
        [none_button(i18n("bot-set-gpa-below"))],
        _row(i18n, "gpa_below", RATING_PRESETS, gpa),
        [none_button(i18n("bot-set-semester-below"))],
        _row(i18n, "sem_below", RATING_PRESETS, semester),
        [none_button(i18n("bot-set-mark-below"))],
        _row(i18n, "mark_below", MARK_PRESETS, mark),
        [cb_button(i18n("bot-btn-back"), open_cb("marks"))],
    ]
