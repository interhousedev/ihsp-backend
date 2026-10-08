"""Subject filter screen of the mark notifications (BOT-13)."""

from collections.abc import Sequence
from uuid import UUID

from app.interfaces.bot.keyboards import settings_subjects
from app.shared.contracts.identity import UserPreferences
from app.shared.contracts.notify import RenderedMessage
from app.shared.i18n.core import I18nContext


def build_settings_subjects(
    prefs: UserPreferences,
    subject_ids: Sequence[UUID],
    names: Sequence[str],
    i18n: I18nContext,
) -> RenderedMessage:
    """Return one toggle per subject; no stored filter means every subject."""
    chosen = prefs.marks_subject_ids
    selected = [chosen is None or subject in chosen for subject in subject_ids]
    return RenderedMessage(
        text_html=i18n("bot-settings-subjects"),
        buttons=settings_subjects.get(i18n, names, selected),
    )
