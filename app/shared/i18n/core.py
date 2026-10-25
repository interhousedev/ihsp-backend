"""Translations loaded from per-language folders (derived from the 21ID bot)."""

import json
from pathlib import Path
from typing import Any, Self

FALLBACK_LOCALE = "ru"


class I18nContext:
    """Translation context for a specific locale."""

    def __init__(
        self,
        translations: dict[str, str],
        locale: str = "en",
        fallback: dict[str, str] | None = None,
    ) -> None:
        """Store the locale's messages and an optional fallback message map."""
        self._translations = translations
        self._fallback = fallback or {}
        self.locale = locale

    def get(self, key: str, **kwargs: Any) -> str:
        """Return the translated string with placeholders filled in.

        Falls back to the fallback locale, then to the key itself.
        """
        text = self._translations.get(key)
        if text is None:
            text = self._fallback.get(key)
        if text is None:
            return key
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, IndexError):
                pass
        return text

    def __call__(self, key: str, **kwargs: Any) -> str:
        """Shortcut for get()."""
        return self.get(key, **kwargs)


class I18nCore:
    """Loads JSON locale files from ``locales_dir/<lang>/*.json`` and merges them."""

    def __init__(
        self, locales_dir: str | Path, default_locale: str = FALLBACK_LOCALE
    ) -> None:
        """Remember the folder; call load() to read it."""
        self.locales_dir = Path(locales_dir)
        self.default_locale = default_locale
        self._translations: dict[str, dict[str, str]] = {}
        self.available_locales: list[str] = []

    def load(self) -> Self:
        """Read every ``<lang>/*.json`` (sorted by name) and merge per language.

        A flat ``<lang>.json`` next to the language folders is merged first.
        """
        self._translations = {}
        if not self.locales_dir.is_dir():
            self.available_locales = []
            return self
        entries = sorted(self.locales_dir.iterdir(), key=lambda p: p.is_dir())
        for entry in entries:
            if entry.is_dir():
                self._merge(entry.name, sorted(entry.glob("*.json")))
            elif entry.suffix == ".json":
                self._merge(entry.stem, [entry])
        self.available_locales = sorted(self._translations)
        return self

    def _merge(self, locale: str, files: list[Path]) -> None:
        messages = self._translations.setdefault(locale, {})
        for path in files:
            with path.open(encoding="utf-8") as handle:
                messages.update(json.load(handle))

    def get_context(self, locale: str) -> I18nContext:
        """Return I18nContext for the locale with the default locale as fallback."""
        return I18nContext(
            translations=self._translations.get(locale, {}),
            locale=locale,
            fallback=self._translations.get(self.default_locale, {}),
        )

    def t(self, locale: str, key: str, **params: Any) -> str:
        """Translate: the locale, then the fallback locale (ru), then the key."""
        return self.get_context(locale).get(key, **params)
