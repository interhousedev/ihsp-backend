"""Localized names with the fallback order uz, ru, en."""

from collections.abc import Mapping

_FALLBACK = ("uz", "ru", "en")


def localized(name: Mapping[str, str | None], locale: str) -> str:
    """Return the name in the locale, else the first non-empty of uz, ru, en."""
    for lang in (locale, *_FALLBACK):
        value = name.get(lang)
        if value:
            return value
    return ""
