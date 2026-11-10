"""Keyboards of the onboarding tour (steps in ``STEPS``)."""

from collections.abc import Iterable

from app.interfaces.bot.callbacks import OnboardingCb
from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.markup import (
    Button,
    Rows,
    cb_button,
    pairs,
    url_button,
    web_app_button,
)
from app.shared.actor import Role
from app.shared.contracts.callbacks import MenuCb, SettingsCb
from app.shared.i18n.core import I18nContext

STEPS = ("welcome", "apps", "settings", "ai")


def apps_for(roles: Iterable[Role], urls: BotUrls) -> list[tuple[str, str]]:
    """(label key, url) of the apps the roles use, without duplicates."""
    held = set(roles)
    apps: list[tuple[str, str]] = []
    if Role.STUDENT in held:
        apps.append(("onboarding-app-sp", urls.sp))
    if Role.TEACHER in held:
        apps.append(("onboarding-app-staff", urls.staff))
    if held & {Role.STUDENT, Role.TEACHER, Role.LMS_ADMIN, Role.LMS_CREATOR}:
        apps.append(("onboarding-app-lms", urls.lms))
    if held & {Role.STUDENT, Role.TEACHER, Role.LIBRARIAN}:
        apps.append(("onboarding-app-library", urls.library))
    if Role.ADMIN in held:
        apps.append(("onboarding-app-admin", urls.admin))
    return apps or [("onboarding-app-sp", urls.sp)]


def _nav(i18n: I18nContext, step: str) -> list[Button]:
    """Back (except on the first step), Next and, always, a way out."""
    index = STEPS.index(step)
    row: list[Button] = []
    if index > 0:
        row.append(cb_button(i18n("bot-btn-back"), OnboardingCb(step=STEPS[index - 1])))
    if index < len(STEPS) - 1:
        row.append(
            cb_button(i18n("onboarding-btn-next"), OnboardingCb(step=STEPS[index + 1]))
        )
    else:
        row.append(cb_button(i18n("onboarding-btn-done"), MenuCb(screen="menu")))
    return row


def get(i18n: I18nContext, step: str, roles: Iterable[Role], urls: BotUrls) -> Rows:
    """Buttons of one step; every step ends with the navigation row."""
    rows: Rows = []
    if step == "apps":
        rows = pairs(
            [web_app_button(i18n(key), url) for key, url in apps_for(roles, urls)]
        )
    elif step == "settings":
        rows = pairs(
            [
                cb_button(
                    i18n("onboarding-btn-language"),
                    SettingsCb(key="open", value="lang"),
                ),
                cb_button(
                    i18n("onboarding-btn-notifications"),
                    SettingsCb(key="open", value="marks"),
                ),
            ]
        )
    elif step == "ai":
        rows = [[url_button(i18n("onboarding-btn-connect-ai"), urls.connectors)]]
    rows.append(_nav(i18n, step))
    if step != STEPS[-1]:
        rows.append([cb_button(i18n("bot-btn-skip"), MenuCb(screen="menu"))])
    return rows
