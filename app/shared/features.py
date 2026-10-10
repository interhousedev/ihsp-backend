"""Feature flags: which parts of the product a deployment runs.

The switches are `FEATURES__<NAME>` in the environment (`app.settings_features`).
Code asks `is_enabled(settings, Feature.NOTEBOOKS)`; the HTTP routers and the cron
schedule use the same helper, so one variable switches a feature everywhere.
"""

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.settings import Settings


class Feature(StrEnum):
    """A switchable part of the product; the value is the `FEATURES__` field name."""

    NOTEBOOKS = "notebooks"
    AI_ASSISTANT = "ai_assistant"
    FLASHCARDS = "flashcards"
    LMS = "lms"
    MAIL = "mail"
    PUSH = "push"
    EMIS_SYNC = "emis_sync"
    LIBRARY = "library"
    WEB_SEARCH = "web_search"
    VECTOR_SEARCH = "vector_search"
    CHANGE_PASSWORD_ON_LOGIN = "change_password_on_login"  # opt-in, off by default


def is_enabled(settings: "Settings", feature: Feature) -> bool:
    """True when the feature is on.

    `NOTEBOOKS__ENABLED=false`, the older switch, still turns notebooks off. Push also
    needs `PUSH__ENABLED` (its keys); that is checked by the push code itself.
    """
    if not getattr(settings.features, feature.value):
        return False
    if feature is Feature.NOTEBOOKS:
        return settings.notebooks.enabled
    return True
