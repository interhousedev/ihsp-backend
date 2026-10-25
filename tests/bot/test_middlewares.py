"""Actor and i18n middlewares; block and unblock updates (BOT-22)."""

from app.interfaces.bot.middlewares.i18n import resolve_locale
from app.shared.contracts.identity import UserStatus
from tests.bot.support.fakes import STUDENT_TG, make_user
from tests.bot.support.harness import Harness

import pytest
from aiogram.types import User


def telegram_user(language: str | None) -> User:
    """A Telegram user with a language code."""
    return User(id=1, is_bot=False, first_name="T", language_code=language)


@pytest.mark.parametrize(
    ("preference", "telegram", "expected"),
    [
        ("uz", "ru", "uz"),
        ("xx", "en-US", "en"),
        (None, "uz", "uz"),
        (None, "de", "ru"),
        (None, None, "ru"),
    ],
)
def test_locale_is_the_preference_then_telegram_then_russian(
    preference: str | None, telegram: str | None, expected: str
) -> None:
    """Locale: user preference, else Telegram language in uz/ru/en, else ru."""
    user = make_user(locale=preference) if preference else None

    assert resolve_locale(user, telegram_user(telegram)) == expected


async def test_unlinked_users_get_the_language_of_their_telegram(
    harness: Harness,
) -> None:
    """An unlinked user's Telegram language_code picks the language."""
    await harness.send("/start", user_id=7777, language="uz")

    assert harness.world.i18n.requested[-1] == "uz"


async def test_linked_users_get_their_preferred_language(harness: Harness) -> None:
    """The stored locale wins over Telegram's."""
    await harness.send("/start", language="uz")

    assert harness.world.i18n.requested[-1] == "en"  # make_user(locale="en")


async def test_a_blocked_mark_is_cleared_when_the_user_writes(
    harness: Harness,
) -> None:
    """UF-BOT-11 step 3: writing to the bot clears the blocked mark."""
    directory = harness.world.directory
    await directory.set_telegram_blocked(STUDENT_TG, True)
    directory.blocked_calls.clear()

    await harness.send("/menu")

    assert directory.blocked_calls == [(STUDENT_TG, False)]


async def test_username_changes_are_remembered(harness: Harness) -> None:
    """The cached Telegram username follows the user."""
    await harness.send("/menu")

    assert harness.world.directory.touch_calls == [(STUDENT_TG, None, "Test")]


async def test_nothing_is_written_when_nothing_changed(harness: Harness) -> None:
    """No writes for an unchanged, unblocked account."""
    await harness.send("/menu")
    harness.world.directory.touch_calls.clear()
    harness.world.directory.blocked_calls.clear()

    await harness.send("/menu")

    assert harness.world.directory.blocked_calls == []


async def test_a_deactivated_user_is_treated_as_unlinked(harness: Harness) -> None:
    """Only active accounts use the bot."""
    harness.world.directory.users[STUDENT_TG] = make_user(status=UserStatus.BLOCKED)

    await harness.send("/menu")

    assert harness.last_text() == "bot-login-welcome"


async def test_blocking_the_bot_marks_the_account(harness: Harness) -> None:
    """BOT-22: a my_chat_member kicked update marks the link blocked."""
    await harness.block(kicked=True)

    assert harness.world.directory.blocked_calls[-1] == (STUDENT_TG, True)


async def test_unblocking_the_bot_clears_the_mark(harness: Harness) -> None:
    """BOT-22: a member update resumes sending."""
    await harness.block(kicked=True)
    await harness.block(kicked=False)

    assert harness.world.directory.blocked_calls[-1] == (STUDENT_TG, False)
    assert harness.world.directory.accounts[STUDENT_TG].blocked is False
