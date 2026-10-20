"""Cancel button of the work-off text input: back to the checklist."""

from app.interfaces.bot.callbacks import WorkOffPromptCb
from app.interfaces.bot.utilities.markup import Rows, cb_button
from app.shared.i18n.core import I18nContext


def get(i18n: I18nContext, lesson: str) -> Rows:
    """Return the Cancel row (every multi-step input has one, BOT-4)."""
    return [
        [
            cb_button(
                i18n("bot-btn-cancel"),
                WorkOffPromptCb(lesson=lesson, action="cancel_text"),
            )
        ]
    ]
