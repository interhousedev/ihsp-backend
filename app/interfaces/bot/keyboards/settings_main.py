"""Settings menu: language, notifications, lessons and Log out (UF-BOT-06)."""

from collections.abc import Iterable

from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.actor import Role
from app.shared.contracts.callbacks import MenuCb, SettingsCb
from app.shared.i18n.core import I18nContext


def open_cb(screen: str) -> SettingsCb:
    """Callback data that opens a settings screen."""
    return SettingsCb(key="open", value=screen)


def get(i18n: I18nContext, roles: Iterable[Role]) -> Rows:
    """Return the settings buttons that apply to the roles."""
    held = set(roles)
    rows: Rows = [[cb_button(i18n("bot-btn-language"), open_cb("lang"))]]
    if Role.STUDENT in held:
        rows.append([cb_button(i18n("bot-btn-notifications"), open_cb("marks"))])
    if held & {Role.STUDENT, Role.TEACHER}:
        rows.append([cb_button(i18n("bot-btn-lesson-settings"), open_cb("lessons"))])
    rows.append(
        [cb_button(i18n("bot-btn-logout"), SettingsCb(key="logout", value="ask"))]
    )
    rows.append([cb_button(i18n("bot-btn-back"), MenuCb(screen="menu"))])
    return rows
