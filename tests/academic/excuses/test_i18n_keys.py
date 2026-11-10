"""Every message key of excuses exists in uz, ru and en."""

import inspect
import json

from app.modules.academic.domain.excuses import errors
from app.shared.base_error import BaseError
from app.shared.paths import LOCALES_DIR

LANGUAGES = ("en", "ru", "uz")


def _messages(lang: str) -> dict[str, str]:
    data: dict[str, str] = json.loads(
        (LOCALES_DIR / lang / "excuses.json").read_text(encoding="utf-8")
    )
    return data


def test_every_error_has_a_translation_in_every_language() -> None:
    keys = {
        cls.message_key
        for _, cls in inspect.getmembers(errors, inspect.isclass)
        if issubclass(cls, BaseError) and cls.__module__ == errors.__name__
    }
    keys.add("attendance-excused-locked")
    for lang in LANGUAGES:
        assert not {k for k in keys if k not in _messages(lang)}, lang


def test_the_three_languages_have_the_same_keys() -> None:
    en = set(_messages("en"))
    assert set(_messages("ru")) == en
    assert set(_messages("uz")) == en
