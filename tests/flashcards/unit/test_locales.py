"""i18n: every error of the module has a message in en, ru and uz."""

import inspect
import json
import re

from app.modules.flashcards.domain import errors
from app.modules.flashcards.domain.errors import InvalidCardsError, InvalidSetError
from app.shared.base_error import BaseError
from app.shared.i18n.core import I18nCore
from app.shared.paths import LOCALES_DIR

import pytest

LANGUAGES = ("en", "ru", "uz")
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _catalogue(language: str) -> dict[str, str]:
    path = LOCALES_DIR / language / "flashcards.json"
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _module_errors() -> list[type[BaseError]]:
    return [
        cls
        for _, cls in inspect.getmembers(errors, inspect.isclass)
        if issubclass(cls, BaseError) and cls.__module__ == errors.__name__
    ]


def test_the_three_languages_have_the_same_keys() -> None:
    """Definition of done: keys of locales/{en,ru,uz}/flashcards.json are equal."""
    keys = {language: set(_catalogue(language)) for language in LANGUAGES}

    assert keys["ru"] == keys["en"]
    assert keys["uz"] == keys["en"]


def test_every_key_has_the_fc_prefix_and_a_text() -> None:
    """§ 3.9: keys of this module start with `fc-`; texts are not empty."""
    for language in LANGUAGES:
        for key, text in _catalogue(language).items():
            assert key.startswith("fc-"), (language, key)
            assert text.strip(), (language, key)


@pytest.mark.parametrize("key", sorted(_catalogue("en")))
def test_a_translation_uses_the_same_placeholders_as_english(key: str) -> None:
    """A message in ru or uz may not lose or invent {placeholders}."""
    expected = set(PLACEHOLDER.findall(_catalogue("en")[key]))

    for language in ("ru", "uz"):
        assert set(PLACEHOLDER.findall(_catalogue(language)[key])) == expected, (
            language,
            key,
        )


def test_the_module_defines_errors() -> None:
    """Guards the discovery used by the tests below."""
    assert len(_module_errors()) == 5


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_error_has_a_message_in_every_language(language: str) -> None:
    """`message_key` of each error exists in locales/<lang>/flashcards.json."""
    i18n = I18nCore(LOCALES_DIR).load()

    for error in _module_errors():
        message = i18n.t(language, error.message_key)
        assert message != error.message_key, (language, error.message_key)


@pytest.mark.parametrize("language", LANGUAGES)
def test_messages_with_parameters_are_filled_in(language: str) -> None:
    """The params the errors carry fill every placeholder of the message."""
    i18n = I18nCore(LOCALES_DIR).load()
    cards = InvalidCardsError(
        params={"reason": "count", "max_cards": 500, "max_chars": 2000}
    )
    fields = InvalidSetError(params={"field": "new_per_day", "min": 1, "max": 200})

    for error in (cards, fields):
        message = i18n.t(language, error.message_key, **error.params)
        assert "{" not in message and "}" not in message, message


def test_error_codes_are_stable_and_prefixed_with_the_module_name() -> None:
    """Problem+json `type`: `flashcards/...` for every error."""
    codes = {cls.code for cls in _module_errors()}

    assert all(code.startswith("flashcards/") for code in codes)
    assert codes == {
        "flashcards/set-not-found",
        "flashcards/card-not-found",
        "flashcards/invalid-cards",
        "flashcards/invalid-set",
        "flashcards/share-not-found",
    }
