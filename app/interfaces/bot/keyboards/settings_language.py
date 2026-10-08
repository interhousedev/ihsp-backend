"""Language picker (BOT-13 settings)."""

from app.interfaces.bot.keyboards.settings_main import open_cb
from app.interfaces.bot.utilities.markup import Rows, cb_button, toggle_text
from app.shared.contracts.callbacks import SettingsCb
from app.shared.i18n.core import I18nContext

# Languages are shown in their own language so everyone can find theirs.
LANGUAGES = (("uz", "Oʻzbekcha"), ("ru", "Русский"), ("en", "English"))


def get(i18n: I18nContext, current: str) -> Rows:
    """Return one button per language with the current one checked."""
    rows: Rows = [
        [
            cb_button(
                toggle_text(name, code == current), SettingsCb(key="lang", value=code)
            )
        ]
        for code, name in LANGUAGES
    ]
    rows.append([cb_button(i18n("bot-btn-back"), open_cb("main"))])
    return rows
