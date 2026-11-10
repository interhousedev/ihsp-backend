"""The hub keyboard: sections by role, then the mini app (BOT-8, BOT-9)."""

from collections.abc import Iterable

from app.interfaces.bot.urls import BotUrls
from app.interfaces.bot.utilities.markup import (
    Button,
    Rows,
    cb_button,
    none_button,
    pairs,
    web_app_button,
)
from app.shared.actor import Role
from app.shared.contracts.callbacks import MenuCb
from app.shared.i18n.core import I18nContext


def _screen(i18n: I18nContext, label: str, screen: str) -> Button:
    return cb_button(i18n(label), MenuCb(screen=screen))


def _section(i18n: I18nContext, title: str, buttons: list[Button]) -> Rows:
    return [[none_button(i18n(title))], *pairs(buttons)]


def study_section(i18n: I18nContext, roles: set[Role], urls: BotUrls) -> Rows:
    """Study for students, Work for teachers: today, lessons, marks, absences."""
    page = urls.page
    if Role.STUDENT in roles:
        buttons = [
            _screen(i18n, "bot-btn-today", "today"),
            _screen(i18n, "bot-btn-marks", "marks"),
            _screen(i18n, "bot-btn-homework", "homework"),
            _screen(i18n, "bot-btn-workoffs", "workoffs"),
            web_app_button(i18n("bot-btn-timetable"), page(roles, "timetable/")),
            web_app_button(i18n("bot-btn-hub-attendance"), page(roles, "attendance/")),
            web_app_button(i18n("bot-btn-excuses"), page(roles, "excuses/")),
        ]
        return _section(i18n, "bot-menu-section-study", buttons)
    buttons = [
        _screen(i18n, "bot-btn-today", "today"),
        _screen(i18n, "bot-btn-current-lesson", "lesson"),
        _screen(i18n, "bot-btn-workoffs", "workoffs"),
        web_app_button(i18n("bot-btn-hub-journal"), page(roles, "journal/")),
        web_app_button(i18n("bot-btn-excuses"), page(roles, "excuses/")),
    ]
    return _section(i18n, "bot-menu-section-work", buttons)


def tools_section(i18n: I18nContext, roles: set[Role], urls: BotUrls) -> Rows:
    """Tools: assistant, notebooks, flashcards, library (and mail for students)."""
    page = urls.page
    buttons = [_screen(i18n, "bot-btn-assistant", "assistant")]
    if Role.STUDENT in roles:
        buttons.append(_screen(i18n, "bot-btn-mail", "mail"))
    buttons.append(web_app_button(i18n("bot-btn-notebooks"), page(roles, "notebooks/")))
    if Role.STUDENT in roles:
        buttons.append(
            web_app_button(i18n("bot-btn-flashcards"), page(roles, "flashcards/"))
        )
    buttons.append(web_app_button(i18n("bot-btn-library"), urls.library))
    return _section(i18n, "bot-menu-section-tools", buttons)


def account_section(i18n: I18nContext, roles: set[Role], urls: BotUrls) -> Rows:
    """Account: notifications, settings, feedback and help."""
    buttons = [
        web_app_button(
            i18n("bot-btn-hub-notifications"), urls.page(roles, "notifications/")
        ),
        _screen(i18n, "bot-btn-settings", "settings"),
        _screen(i18n, "bot-btn-feedback", "feedback"),
        _screen(i18n, "bot-btn-help", "help"),
    ]
    return _section(i18n, "bot-menu-section-account", buttons)


def get(i18n: I18nContext, roles: Iterable[Role], urls: BotUrls) -> Rows:
    """Return the hub rows: sections by role and the Open app button."""
    held = set(roles)
    rows: Rows = []
    if held & {Role.STUDENT, Role.TEACHER}:
        rows.extend(study_section(i18n, held, urls))
        rows.extend(tools_section(i18n, held, urls))
    rows.extend(account_section(i18n, held, urls))
    rows.append([web_app_button(i18n("bot-btn-open-app"), urls.app_for(held))])
    return rows
