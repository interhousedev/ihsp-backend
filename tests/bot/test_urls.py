"""BOT-8: which mini app a role opens, and the links the bot builds."""

from app.interfaces.bot.urls import BotUrls
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.ids import new_id

import pytest

URLS = BotUrls.from_settings(UrlsSettings())


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ({Role.STUDENT}, "http://localhost:3002"),
        ({Role.TEACHER}, "http://localhost:3003"),
        ({Role.STUDENT, Role.TEACHER}, "http://localhost:3003"),
        ({Role.ADMIN}, "http://localhost:3004"),
        ({Role.LMS_ADMIN}, "http://localhost:3005"),
        (set(), "http://localhost:3002"),
    ],
)
def test_the_mini_app_follows_the_role(roles: set[Role], expected: str) -> None:
    """Students open IHSP Web, teachers the staff portal (BOT-8)."""
    assert URLS.app_for(roles) == expected


def test_lesson_links_point_to_the_app_of_the_role() -> None:
    """Lessons open in the app that fits the user."""
    lesson_id = new_id()

    assert URLS.lesson({Role.STUDENT}, lesson_id) == (
        f"http://localhost:3002/lessons/view/?id={lesson_id}"
    )
    assert URLS.staff_lesson(lesson_id) == (
        f"http://localhost:3003/lessons/view/?id={lesson_id}"
    )


def test_login_and_security_pages_are_on_the_id_service() -> None:
    """ID-19: the Log in button opens {URLS__ID}/telegram/."""
    assert URLS.login == "http://localhost:3001/telegram/"
    assert URLS.security == "http://localhost:3001/security/"


def test_a_trailing_slash_in_settings_does_not_double() -> None:
    """Origins from settings may end with a slash."""
    urls = BotUrls.from_settings(UrlsSettings(id="https://id.ihsu.uz/"))

    assert urls.login == "https://id.ihsu.uz/telegram/"
