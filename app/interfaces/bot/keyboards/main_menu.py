"""Main menu keyboard, built from the user's roles (BOT-8, BOT-9)."""

from collections.abc import Iterable

from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.markup import (
    Button,
    Rows,
    cb_button,
    pairs,
    web_app_button,
)
from app.shared.actor import Role
from app.shared.contracts.callbacks import MenuCb
from app.shared.i18n.core import I18nContext

STUDENT_SCREENS = ("today", "marks", "homework", "workoffs", "mail")
TEACHER_SCREENS = ("today", "lesson", "workoffs")
LABELS = {
    "today": "bot-btn-today",
    "marks": "bot-btn-marks",
    "homework": "bot-btn-homework",
    "mail": "bot-btn-mail",
    "lesson": "bot-btn-current-lesson",
    "workoffs": "bot-btn-workoffs",
}


def screens_for(roles: Iterable[Role]) -> list[str]:
    """Return the menu screens for the roles, without duplicates."""
    held = set(roles)
    screens: list[str] = []
    if Role.STUDENT in held:
        screens.extend(STUDENT_SCREENS)
    if Role.TEACHER in held:
        screens.extend(s for s in TEACHER_SCREENS if s not in screens)
    return screens


def get(i18n: I18nContext, roles: Iterable[Role], urls: BotUrls) -> Rows:
    """Return the menu rows: role screens, Settings and Open app."""
    held = list(roles)
    buttons: list[Button] = [
        cb_button(i18n(LABELS[screen]), MenuCb(screen=screen))
        for screen in screens_for(held)
    ]
    buttons.append(cb_button(i18n("bot-btn-feedback"), MenuCb(screen="feedback")))
    buttons.append(cb_button(i18n("bot-btn-settings"), MenuCb(screen="settings")))
    rows = pairs(buttons)
    rows.append([web_app_button(i18n("bot-btn-open-app"), urls.app_for(held))])
    return rows
