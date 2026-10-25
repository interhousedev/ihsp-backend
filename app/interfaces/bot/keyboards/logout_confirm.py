"""Confirmation of Log out (UF-BOT-10)."""

from app.interfaces.bot.keyboards.settings_main import open_cb
from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.contracts.callbacks import SettingsCb
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext) -> Rows:
    """Return Yes, log out and Cancel."""
    return [
        [
            cb_button(
                i18n("bot-btn-logout-yes"), SettingsCb(key="logout", value="yes")
            ),
            cb_button(i18n("bot-btn-cancel"), open_cb("main")),
        ]
    ]
