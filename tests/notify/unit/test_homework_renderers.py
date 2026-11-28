"""Homework notices to the teacher (submitted) and the student (reviewed)."""

from typing import Any

from app.modules.notify.application.renderers.homework_reviewed import (
    HomeworkReviewedRenderer,
)
from app.modules.notify.application.renderers.homework_submitted import (
    HomeworkSubmittedRenderer,
)
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.contracts.notify import RenderContext
from app.shared.i18n.core import I18nCore
from tests.bot.support.fakes import make_user

import pytest

URLS = UrlsSettings()
SUBMITTED: dict[str, Any] = {
    "lesson_id": "l1",
    "submission_id": "s1",
    "student_name": "Ali <b>",
    "subject_names": ["Math & Co"],
    "group_name": "10A",
    "lesson_date": "2026-11-27",
    "late": True,
    "file_count": 3,
}
REVIEWED: dict[str, Any] = {
    "lesson_id": "l1",
    "subject_names": ["Math"],
    "lesson_date": "2026-11-27",
    "review_status": "graded",
    "grade": 5,
    "comment_preview": "Good <i>work</i>",
}


def _ctx(locale: str, role: Role) -> RenderContext:
    return RenderContext(user=make_user(role), locale=locale, telegram_user_id=1)


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
async def test_submitted_notice(i18n: I18nCore, locale: str) -> None:
    message = await HomeworkSubmittedRenderer(i18n, URLS)(
        SUBMITTED, _ctx(locale, Role.TEACHER)
    )

    assert message is not None and message.buttons is not None
    assert "Ali &lt;b&gt;" in message.text_html and "Math &amp; Co" in message.text_html
    assert "27.11" in message.text_html and "10A" in message.text_html
    assert "notify-" not in message.text_html
    button = message.buttons[0][0]
    assert "notify-" not in button["text"]
    link = button.get("web_app_url") or button["url"]
    assert link.endswith("/lessons/view/?id=l1#homework-submissions")


async def test_submitted_without_late_has_no_late_suffix(i18n: I18nCore) -> None:
    on_time = {**SUBMITTED, "late": False}
    message = await HomeworkSubmittedRenderer(i18n, URLS)(
        on_time, _ctx("en", Role.TEACHER)
    )

    assert message is not None and "late" not in message.text_html


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
async def test_reviewed_graded_has_grade_and_quote(i18n: I18nCore, locale: str) -> None:
    message = await HomeworkReviewedRenderer(i18n, URLS)(
        REVIEWED, _ctx(locale, Role.STUDENT)
    )

    assert message is not None and message.buttons is not None
    assert "5" in message.text_html.splitlines()[2]
    assert "<blockquote>Good &lt;i&gt;work&lt;/i&gt;</blockquote>" in message.text_html
    assert "notify-" not in message.text_html
    button = message.buttons[0][0]
    link = button.get("web_app_url") or button["url"]
    assert link.endswith("/homework/?lesson=l1")


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
async def test_reviewed_returned_has_no_grade_line(i18n: I18nCore, locale: str) -> None:
    payload = {**REVIEWED, "review_status": "returned", "grade": None}
    message = await HomeworkReviewedRenderer(i18n, URLS)(
        payload, _ctx(locale, Role.STUDENT)
    )
    graded = await HomeworkReviewedRenderer(i18n, URLS)(
        REVIEWED, _ctx(locale, Role.STUDENT)
    )

    assert message is not None and graded is not None
    assert len(message.text_html.splitlines()) == 3  # title, lesson, quote
    assert message.text_html.splitlines()[0] != graded.text_html.splitlines()[0]
