"""Every error of course authoring has a message in all three languages."""

import inspect
import json
from pathlib import Path

from app.modules.lms.domain.authoring import errors
from app.shared.base_error import BaseError
from app.shared.paths import LOCALES_DIR

import pytest

LANGUAGES = ("en", "ru", "uz")


def _message_keys() -> set[str]:
    classes = [
        c
        for _, c in inspect.getmembers(errors, inspect.isclass)
        if issubclass(c, BaseError) and c.__module__ == errors.__name__
    ]
    return {c.message_key for c in classes}


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_error_message_key_is_translated(language: str) -> None:
    """i18n: `locales/<lang>/lms_authoring.json` covers each error class."""
    path = Path(LOCALES_DIR) / language / "lms_authoring.json"

    messages = json.loads(path.read_text(encoding="utf-8"))

    assert _message_keys() - set(messages) == set()
    assert all(isinstance(v, str) and v for v in messages.values())


def test_all_languages_define_the_same_keys() -> None:
    """No language lags behind."""
    key_sets = [
        set(
            json.loads(
                (Path(LOCALES_DIR) / lang / "lms_authoring.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        for lang in LANGUAGES
    ]

    assert key_sets[0] == key_sets[1] == key_sets[2]
