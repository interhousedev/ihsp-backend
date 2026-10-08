"""Build the settings screen that a button name refers to."""

from app.interfaces.bot.screens.settings_language import build_settings_language
from app.interfaces.bot.screens.settings_lessons import build_settings_lessons
from app.interfaces.bot.screens.settings_main import build_settings_main
from app.interfaces.bot.screens.settings_marks import build_settings_marks
from app.interfaces.bot.screens.settings_subjects import build_settings_subjects
from app.interfaces.bot.screens.settings_thresholds import build_settings_thresholds
from app.interfaces.bot.services import BotServices
from app.shared.contracts.identity import UserRef
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


async def render_subjects(
    user: UserRef, services: BotServices, i18n: I18nContext
) -> RenderedMessage:
    """Subjects come from the student's standing; the order is stable."""
    prefs = await services.directory.get_preferences(user.id)
    summary = await services.marks.subjects_summary(user.id, None)
    ordered = sorted(
        summary, key=lambda item: (item.name.lower(), str(item.subject_id))
    )
    return build_settings_subjects(
        prefs,
        [item.subject_id for item in ordered],
        [item.name for item in ordered],
        i18n,
    )


async def render_settings_screen(
    screen: str, user: UserRef, services: BotServices, i18n: I18nContext
) -> RenderedMessage:
    """Return the screen of a settings button.

    Names are ``main``, ``lang``, ``marks``, ``subjects``, ``thresholds`` and
    ``lessons``; an unknown name gives the overview.
    """
    if screen == "subjects":
        return await render_subjects(user, services, i18n)
    prefs = await services.directory.get_preferences(user.id)
    if screen == "lang":
        return build_settings_language(prefs, i18n)
    if screen == "marks":
        return build_settings_marks(prefs, i18n)
    if screen == "thresholds":
        return build_settings_thresholds(prefs, i18n)
    if screen == "lessons":
        return build_settings_lessons(user, prefs, i18n)
    return build_settings_main(user, prefs, i18n)
