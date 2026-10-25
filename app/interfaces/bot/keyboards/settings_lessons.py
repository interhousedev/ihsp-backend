"""Lesson settings: link lead time and, for teachers, the end-of-lesson prompt."""

from collections.abc import Iterable

from app.interfaces.bot.keyboards.settings_main import open_cb
from app.interfaces.bot.settings_patch import LEAD_MINUTES
from app.interfaces.bot.utilities.markup import (
    Rows,
    cb_button,
    none_button,
    toggle_text,
)
from app.shared.actor import Role
from app.shared.contracts.callbacks import SettingsCb
from app.shared.contracts.identity import UserPreferences
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext, prefs: UserPreferences, roles: Iterable[Role]) -> Rows:
    """Return lead time choices and (teachers) the prompt toggle."""
    rows: Rows = [
        [none_button(i18n("bot-set-lead"))],
        [
            cb_button(
                toggle_text(
                    i18n("bot-set-minutes", minutes=minutes),
                    prefs.lessons_links_lead_min == minutes,
                ),
                SettingsCb(key="lead", value=str(minutes)),
            )
            for minutes in LEAD_MINUTES
        ],
    ]
    if Role.TEACHER in set(roles):
        press = "0" if prefs.lessons_prompt_enabled else "1"
        rows.append(
            [
                cb_button(
                    toggle_text(i18n("bot-set-prompt"), prefs.lessons_prompt_enabled),
                    SettingsCb(key="prompt", value=press),
                )
            ]
        )
    rows.append([cb_button(i18n("bot-btn-back"), open_cb("main"))])
    return rows
