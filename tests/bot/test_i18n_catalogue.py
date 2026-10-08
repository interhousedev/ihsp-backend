"""CODESTYLE: no hardcoded texts; every key exists in uz, ru and en."""

import json
import re
from dataclasses import replace
from pathlib import Path
from string import Formatter

from app.shared.i18n.core import I18nCore
from app.shared.paths import LOCALES_DIR
from tests.bot.support.fakes import STUDENT_TG, TEACHER_TG, World
from tests.bot.support.harness import Harness

import pytest

BOT_SOURCE = Path(__file__).parents[2] / "app" / "interfaces" / "bot"
KEY = re.compile(r"""["']((?:bot|error)-[a-z0-9-]+)["']""")
LANGUAGES = ("en", "ru", "uz")


def used_keys() -> set[str]:
    """Every i18n key literal in the bot source (bot-* only)."""
    found: set[str] = set()
    for path in BOT_SOURCE.rglob("*.py"):
        found.update(KEY.findall(path.read_text(encoding="utf-8")))
    return {key for key in found if key.startswith("bot-")}


def catalogue(language: str) -> dict[str, str]:
    """The bot.json of one language."""
    path = LOCALES_DIR / language / "bot.json"
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def placeholders(text: str) -> set[str]:
    """Names of the ``{param}`` fields in a message."""
    return {name for _, name, _, _ in Formatter().parse(text) if name}


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_key_used_in_code_exists(language: str) -> None:
    """Missing keys would show up as raw keys in the chat."""
    missing = used_keys() - set(catalogue(language))

    assert not missing, sorted(missing)


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_key_is_unused(language: str) -> None:
    """Dead keys are noise; the files list exactly what the code uses."""
    unused = set(catalogue(language)) - used_keys()

    assert not unused, sorted(unused)


def test_the_three_languages_have_the_same_keys() -> None:
    """CODESTYLE definition of done: i18n keys for all three languages."""
    english = set(catalogue("en"))

    assert set(catalogue("ru")) == english
    assert set(catalogue("uz")) == english


def test_translations_use_the_same_parameters() -> None:
    """A translation that drops or renames a parameter would lose information."""
    english = catalogue("en")
    for language in ("ru", "uz"):
        for key, text in catalogue(language).items():
            assert placeholders(text) == placeholders(english[key]), (language, key)


def test_every_key_has_the_bot_prefix() -> None:
    """FINAL_PLAN § 3.9: the bot's keys start with bot-."""
    assert all(key.startswith("bot-") for key in catalogue("en"))


@pytest.mark.parametrize("locale", LANGUAGES)
async def test_screens_render_without_raw_keys_in_every_language(
    harness: Harness, world: World, locale: str
) -> None:
    """With real translations no message or button shows a raw key."""
    world.container.i18n = I18nCore(LOCALES_DIR).load()
    for telegram_id in (STUDENT_TG, TEACHER_TG):
        user = world.directory.users[telegram_id]
        world.directory.users[telegram_id] = replace(user, locale=locale)
    commands = [
        ("/start", STUDENT_TG),
        ("/today", STUDENT_TG),
        ("/marks", STUDENT_TG),
        ("/homework", STUDENT_TG),
        ("/mail", STUDENT_TG),
        ("/settings", STUDENT_TG),
        ("m:lesson", TEACHER_TG),
        ("st:open:marks", STUDENT_TG),
        ("st:open:thresholds", STUDENT_TG),
        ("st:open:lessons", TEACHER_TG),
        ("st:open:lang", STUDENT_TG),
        ("st:logout:ask", STUDENT_TG),
        ("mc:new", STUDENT_TG),
    ]

    for data, user_id in commands:
        if data.startswith("/"):
            await harness.send(data, user_id=user_id)
        else:
            await harness.press(data, user_id=user_id)
        assert "bot-" not in harness.last_text(), (locale, data)
        assert not [x for x in harness.last_labels() if "bot-" in x], (locale, data)
