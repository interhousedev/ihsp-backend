"""Localized names with the project fallback order (uz, ru, en)."""

from collections.abc import Mapping

FALLBACK_ORDER = ("uz", "ru", "en")


def localized(names: Mapping[str, str] | None, locale: str) -> str:
    """Pick the name in the locale, then uz, ru, en; empty string if none."""
    if not names:
        return ""
    for key in (locale, *FALLBACK_ORDER):
        value = names.get(key)
        if value:
            return value
    return next((value for value in names.values() if value), "")
