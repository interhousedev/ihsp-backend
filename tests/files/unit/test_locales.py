"""i18n: every error of the module has a message in en, ru and uz."""

import inspect

from app.modules.files.domain import errors
from app.shared.base_error import BaseError
from app.shared.i18n.core import I18nCore
from app.shared.paths import LOCALES_DIR

import pytest

LANGUAGES = ("en", "ru", "uz")


def _module_errors() -> list[type[BaseError]]:
    return [
        cls
        for _, cls in inspect.getmembers(errors, inspect.isclass)
        if issubclass(cls, BaseError) and cls.__module__ == errors.__name__
    ]


def test_the_module_defines_errors() -> None:
    """Guards the discovery used by the tests below."""
    assert len(_module_errors()) >= 10


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_error_has_a_message_in_every_language(language: str) -> None:
    """``message_key`` of each error exists in locales/<lang>/files.json."""
    i18n = I18nCore(LOCALES_DIR).load()

    for error in _module_errors():
        message = i18n.t(language, error.message_key, max_length=255)
        assert message != error.message_key, (language, error.message_key)


def test_error_codes_are_stable_and_prefixed_with_the_module_name() -> None:
    """Problem+json ``type`` values: ``files/…`` for every error."""
    codes = {cls.code for cls in _module_errors()}

    assert all(code.startswith("files/") for code in codes)
    assert {
        "files/quota-exceeded",
        "files/type-not-allowed",
        "files/too-large",
        "files/upload-missing",
    } <= codes
