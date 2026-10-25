"""MAIL-4, MAIL-6, MAIL-8: every mail error has a message in uz, ru and en."""

import json

from app.modules.mail.domain import errors
from app.shared.base_error import BaseError
from app.shared.paths import LOCALES_DIR

import pytest

MAIL_ERRORS = [
    cls
    for cls in vars(errors).values()
    if isinstance(cls, type)
    and issubclass(cls, BaseError)
    and cls.__module__ == errors.__name__
]


def test_the_module_defines_its_errors() -> None:
    """Sanity: the collection above found them."""
    assert len(MAIL_ERRORS) == 14


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
def test_every_error_key_exists_in_the_mail_locale_file(locale: str) -> None:
    """MAIL-*: locales/<lang>/mail.json has a text for each message_key."""
    messages = json.loads((LOCALES_DIR / locale / "mail.json").read_text("utf-8"))

    for cls in MAIL_ERRORS:
        assert cls.message_key in messages, (locale, cls.message_key)
        assert cls.message_key.startswith("mail-")


def test_the_three_languages_have_the_same_keys_and_placeholders() -> None:
    """MAIL-*: no key or {placeholder} exists in one language only."""
    files = {
        locale: json.loads((LOCALES_DIR / locale / "mail.json").read_text("utf-8"))
        for locale in ("en", "ru", "uz")
    }

    assert files["en"].keys() == files["ru"].keys() == files["uz"].keys()
    for key in files["en"]:
        placeholders = {
            locale: {p for p in ("{limit}", "{address}") if p in messages[key]}
            for locale, messages in files.items()
        }
        assert placeholders["en"] == placeholders["ru"] == placeholders["uz"], key


def test_error_codes_are_unique_and_namespaced() -> None:
    """The problem+json `type` of the mail module starts with mail/."""
    codes = [cls.code for cls in MAIL_ERRORS]

    assert len(set(codes)) == len(codes)
    assert all(code.startswith("mail/") for code in codes)
