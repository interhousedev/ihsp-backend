"""GEN-3, definition of done: every i18n key of task B1 exists in uz, ru and en."""

import json
from pathlib import Path

from app.modules.identity.domain import errors
from app.modules.identity.infrastructure.mailer.smtp import TEMPLATES
from app.shared.base_error import BaseError
from app.shared.paths import LOCALES_DIR

import pytest

LANGS = ("en", "ru", "uz")
ROOT = Path(__file__).resolve().parents[3] / "app"
B1_SOURCES = [
    *ROOT.joinpath("modules/identity").glob("domain/*.py"),
    *ROOT.joinpath("modules/identity").glob("application/*.py"),
    *ROOT.joinpath("modules/identity").glob("infrastructure/**/*.py"),
    *ROOT.joinpath("modules/identity").glob("infrastructure/mailer/templates/*.html"),
]


def load(lang: str) -> dict[str, str]:
    """The id.json file of a language."""
    return json.loads((LOCALES_DIR / lang / "id.json").read_text(encoding="utf-8"))


def merged(lang: str) -> dict[str, str]:
    """All files of a language, as I18nCore merges them."""
    result: dict[str, str] = {}
    for path in sorted((LOCALES_DIR / lang).glob("*.json")):
        result.update(json.loads(path.read_text(encoding="utf-8")))
    return result


def test_the_three_languages_have_the_same_keys() -> None:
    """No key is missing in a language."""
    keys = {lang: set(load(lang)) for lang in LANGS}

    assert keys["ru"] == keys["en"] == keys["uz"]
    assert all(key.startswith("id-") for key in keys["en"])


@pytest.mark.parametrize("lang", LANGS)
def test_no_translation_is_empty_and_placeholders_match_english(lang: str) -> None:
    """Placeholders like {code} must survive translation."""
    import re

    english, other = load("en"), load(lang)
    for key, text in other.items():
        assert text.strip(), key
        assert set(re.findall(r"{(\w+)}", text)) == set(
            re.findall(r"{(\w+)}", english[key])
        ), key


@pytest.mark.parametrize("lang", LANGS)
def test_every_identity_error_has_a_message(lang: str) -> None:
    """Every error class of the module points at an existing key."""
    messages = merged(lang)
    classes = [
        c
        for c in vars(errors).values()
        if isinstance(c, type)
        and issubclass(c, BaseError)
        and c.__module__ == errors.__name__
    ]

    assert classes
    for error_class in classes:
        assert error_class.message_key in messages, error_class.__name__


@pytest.mark.parametrize("lang", LANGS)
def test_every_email_template_has_a_subject(lang: str) -> None:
    """The subject key follows the template name."""
    messages = merged(lang)

    for template in TEMPLATES:
        assert f"id-mail-{template.replace('_', '-')}-subject" in messages


@pytest.mark.parametrize("lang", LANGS)
def test_every_id_key_used_in_the_module_exists(lang: str) -> None:
    """Keys written in code or templates are translated."""
    import re

    messages = merged(lang)
    used = set()
    for path in B1_SOURCES:
        used |= set(re.findall(r'"(id-[a-z0-9-]+)"', path.read_text(encoding="utf-8")))
    missing = {key for key in used if key not in messages}

    assert not missing
