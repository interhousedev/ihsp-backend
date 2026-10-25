"""Every message key the classwork area uses exists in uz, ru and en."""

import inspect
import json

from app.modules.academic.domain.classwork import errors
from app.shared.base_error import BaseError
from app.shared.paths import LOCALES_DIR

LANGUAGES = ("en", "ru", "uz")


def _messages(lang: str) -> dict[str, str]:
    path = LOCALES_DIR / lang / "academic_classwork.json"
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_every_error_has_a_translation_in_every_language() -> None:
    """CODESTYLE: i18n keys added for all three languages."""
    keys = {
        cls.message_key
        for _, cls in inspect.getmembers(errors, inspect.isclass)
        if issubclass(cls, BaseError) and cls.__module__ == errors.__name__
    }

    for lang in LANGUAGES:
        missing = {key for key in keys if key not in _messages(lang)}
        assert not missing, f"{lang}: {sorted(missing)}"


def test_the_three_languages_have_the_same_keys() -> None:
    """No key is translated into one language only."""
    en = set(_messages("en"))

    assert set(_messages("ru")) == en
    assert set(_messages("uz")) == en
    assert all(key.startswith(("academic-", "attendance-", "homework-")) for key in en)


def test_placeholders_match_between_languages() -> None:
    """A {days} or {max} placeholder must exist in every translation."""
    en = _messages("en")
    for lang in ("ru", "uz"):
        other = _messages(lang)
        for key, text in en.items():
            for name in ("days", "max"):
                assert ("{%s}" % name in text) == ("{%s}" % name in other[key]), key
