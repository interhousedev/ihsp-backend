"""i18n: every key used by task B2 exists in uz, ru and en."""

import inspect
import json
from pathlib import Path

from app.modules.identity.application import register_errors
from app.modules.identity.domain.password_policy import check_password
from app.shared.base_error import BaseError
from app.shared.contracts.emis import EmisAuthFailed, EmisUnavailable
from app.shared.paths import LOCALES_DIR

import pytest

LANGUAGES = ("en", "ru", "uz")
NOTICE_KEYS = ("id-mail-reclaimed-notice", "id-mail-deleted-notice")


def used_keys() -> set[str]:
    errors = [
        cls
        for _, cls in inspect.getmembers(register_errors, inspect.isclass)
        if issubclass(cls, BaseError) and cls.__module__ == register_errors.__name__
    ]
    keys = {cls.message_key for cls in errors}
    keys |= {EmisAuthFailed.message_key, EmisUnavailable.message_key}
    keys |= set(check_password(""))
    keys |= set(NOTICE_KEYS)
    return keys


def load(language: str) -> dict[str, str]:
    path = Path(LOCALES_DIR) / language / "id_registration.json"
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_used_key_has_a_translation(language: str) -> None:
    """Definition of done: i18n keys exist for all three languages."""
    messages = load(language)

    missing = {key for key in used_keys() if not messages.get(key, "").strip()}

    assert missing == set()


def test_the_three_languages_have_the_same_keys() -> None:
    """No key is translated in one language only."""
    key_sets = {language: set(load(language)) for language in LANGUAGES}

    assert key_sets["ru"] == key_sets["en"] == key_sets["uz"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_deletion_notice_has_its_date_placeholder(language: str) -> None:
    """ID-29: the email says when the data is removed."""
    assert "{closes_on}" in load(language)["id-mail-deleted-notice"]
