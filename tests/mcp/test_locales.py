"""Every i18n key of the MCP interface exists in en, ru and uz."""

import inspect
import json
import re
from pathlib import Path

from app.interfaces.mcp import errors
from app.shared.base_error import BaseError
from app.shared.paths import LOCALES_DIR

import pytest

LANGUAGES = ("en", "ru", "uz")
PLACEHOLDER = re.compile(r"{(\w+)}")


def _load(language: str) -> dict[str, str]:
    path = Path(LOCALES_DIR) / language / "mcp.json"
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _error_keys() -> set[str]:
    classes = [
        member
        for _, member in inspect.getmembers(errors, inspect.isclass)
        if issubclass(member, BaseError) and member.__module__ == errors.__name__
    ]
    return {cls.message_key for cls in classes}


def test_all_languages_have_the_same_keys() -> None:
    """All three languages are complete."""
    keys = {language: set(_load(language)) for language in LANGUAGES}

    assert keys["ru"] == keys["en"]
    assert keys["uz"] == keys["en"]


def test_every_key_has_the_mcp_prefix_and_text() -> None:
    """Own prefix, no empty strings."""
    for language in LANGUAGES:
        for key, text in _load(language).items():
            assert key.startswith("mcp-")
            assert text.strip()


def test_error_classes_and_prompts_are_translated() -> None:
    """Keys used by errors.py, the guard and the server instructions exist."""
    used = _error_keys() | {
        "mcp-internal-error",
        "mcp-instructions-student",
        "mcp-instructions-lms",
        "mcp-instructions-admin",
    }

    for language in LANGUAGES:
        assert used <= set(_load(language)), language


@pytest.mark.parametrize("language", ["ru", "uz"])
def test_translations_keep_the_placeholders(language: str) -> None:
    """A translation never drops or renames a {parameter}."""
    english = _load("en")
    translated = _load(language)

    for key, text in english.items():
        assert set(PLACEHOLDER.findall(translated[key])) == set(
            PLACEHOLDER.findall(text)
        ), key
