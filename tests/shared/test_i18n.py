"""Translations merged from per-language folders."""

import json
from pathlib import Path

from app.shared import base_error
from app.shared.base_error import BaseError
from app.shared.i18n.core import I18nCore
from app.shared.paths import LOCALES_DIR

import pytest


def write(root: Path, locale: str, name: str, data: dict[str, str]) -> None:
    """Write locales/<locale>/<name>.json."""
    folder = root / locale
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_files_of_one_language_are_merged(tmp_path: Path) -> None:
    """Each task writes its own file; load() merges every *.json of a language."""
    write(tmp_path, "en", "common", {"common-yes": "Yes"})
    write(tmp_path, "en", "bot", {"bot-hello": "Hello, {name}!"})

    i18n = I18nCore(tmp_path).load()

    assert i18n.t("en", "common-yes") == "Yes"
    assert i18n.t("en", "bot-hello", name="Ann") == "Hello, Ann!"
    assert i18n.available_locales == ["en"]


def test_a_missing_key_falls_back_to_russian_then_to_the_key(tmp_path: Path) -> None:
    """Fallback order: locale, ru, the key itself."""
    write(tmp_path, "ru", "common", {"common-yes": "Да"})
    write(tmp_path, "uz", "common", {"common-no": "Yo'q"})

    i18n = I18nCore(tmp_path).load()

    assert i18n.t("uz", "common-no") == "Yo'q"
    assert i18n.t("uz", "common-yes") == "Да"
    assert i18n.t("uz", "unknown-key") == "unknown-key"
    assert i18n.t("fr", "common-yes") == "Да"


def test_missing_params_leave_the_text_unformatted(tmp_path: Path) -> None:
    """A broken placeholder never raises."""
    write(tmp_path, "en", "a", {"k": "Hi {name}"})

    i18n = I18nCore(tmp_path).load()

    assert i18n.t("en", "k") == "Hi {name}"
    assert i18n.t("en", "k", other=1) == "Hi {name}"
    assert i18n.get_context("en")("k", name="Bo") == "Hi Bo"


def test_a_missing_folder_loads_nothing(tmp_path: Path) -> None:
    """No locales yet is not an error."""
    i18n = I18nCore(tmp_path / "nope").load()

    assert i18n.available_locales == []
    assert i18n.t("en", "x") == "x"


def test_every_error_class_has_a_message_in_all_three_languages() -> None:
    """Step 12: error-* keys for every error of the kernel."""
    i18n = I18nCore(LOCALES_DIR).load()
    errors = [
        cls
        for cls in vars(base_error).values()
        if isinstance(cls, type) and issubclass(cls, BaseError)
    ]

    for locale in ("en", "ru", "uz"):
        for cls in errors:
            assert i18n.t(locale, cls.message_key) != cls.message_key, (
                locale,
                cls.message_key,
            )


@pytest.mark.parametrize("key", ["common-yes", "common-no", "common-cancel"])
def test_common_basics_exist_in_all_languages(key: str) -> None:
    """The common-* basics used by the bot and web."""
    i18n = I18nCore(LOCALES_DIR).load()

    assert {i18n.t(locale, key) for locale in ("en", "ru", "uz")} != {key}
    assert all(i18n.t(locale, key) != key for locale in ("en", "ru", "uz"))
