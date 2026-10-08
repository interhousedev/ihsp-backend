"""Mark notification settings: types, values, drops and links to subjects and limits."""

from app.interfaces.bot.keyboards.settings_main import open_cb
from app.interfaces.bot.settings_patch import MARK_TYPES, MARK_VALUES
from app.interfaces.bot.utilities.formatting import MARK_TYPE_KEYS
from app.interfaces.bot.utilities.markup import Rows, cb_button, toggle_text
from app.shared.contracts.callbacks import SettingsCb
from app.shared.contracts.identity import UserPreferences
from app.shared.i18n.core import I18nContext


def _flag(value: bool) -> str:
    return "0" if value else "1"  # the value a press sets: the opposite of now


def get(i18n: I18nContext, prefs: UserPreferences) -> Rows:
    """Return the toggles of the mark notification settings."""
    enabled = SettingsCb(key="marks_enabled", value=_flag(prefs.marks_enabled))
    drops = SettingsCb(key="drops", value=_flag(prefs.alerts_drops))
    rows: Rows = [
        [
            cb_button(
                toggle_text(i18n("bot-set-marks-enabled"), prefs.marks_enabled), enabled
            )
        ],
        [
            cb_button(
                toggle_text(i18n(MARK_TYPE_KEYS[kind]), kind in prefs.marks_types),
                SettingsCb(key="type", value=kind),
            )
            for kind in MARK_TYPES
        ],
        [
            cb_button(
                toggle_text(str(value), value in prefs.marks_values),
                SettingsCb(key="value", value=str(value)),
            )
            for value in MARK_VALUES
        ],
        [cb_button(i18n("bot-btn-subjects"), open_cb("subjects"))],
        [cb_button(toggle_text(i18n("bot-set-drops"), prefs.alerts_drops), drops)],
        [cb_button(i18n("bot-btn-thresholds"), open_cb("thresholds"))],
        [cb_button(i18n("bot-btn-back"), open_cb("main"))],
    ]
    return rows
