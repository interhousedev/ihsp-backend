"""An i18n fake that returns keys, so tests assert on keys (CODESTYLE: bot tests)."""

from typing import Any

from app.shared.i18n.core import I18nContext, I18nCore


class KeyI18nContext(I18nContext):
    """``get`` returns the key, with the parameters appended in sorted order."""

    def __init__(self, locale: str = "en") -> None:
        """No translations; remember the locale."""
        super().__init__({}, locale)

    def get(self, key: str, **kwargs: Any) -> str:
        """Return ``key`` or ``key[a=1,b=2]``."""
        if not kwargs:
            return key
        params = ",".join(f"{name}={kwargs[name]}" for name in sorted(kwargs))
        return f"{key}[{params}]"


class KeyI18nCore(I18nCore):
    """Core whose contexts are KeyI18nContext; records the requested locales."""

    def __init__(self) -> None:
        """No folder to load."""
        super().__init__("/nonexistent")
        self.requested: list[str] = []

    def get_context(self, locale: str) -> I18nContext:
        """Return a key-returning context for the locale."""
        self.requested.append(locale)
        return KeyI18nContext(locale)
