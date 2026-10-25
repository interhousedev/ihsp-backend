"""The assessment_reminder notification: web text, link and the Telegram renderer."""

from typing import Any

from app.modules.notify.application.describe import describe
from app.modules.notify.application.renderers.builtin import register_builtin_renderers
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.contracts.notify import RenderContext
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.factories.notify import make_user
from tests.fakes.notify.files import FakeFilesApi
from tests.fakes.notify.links import FakeLinksApi

import pytest

URLS = UrlsSettings()
ID = str(new_id())


def _payload(**kwargs: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "assessment_id": ID,
        "subject_name": "Mathematics",
        "kind": "midterm",
        "control": "midterm_1",
        "title": "Algebra",
        "date": "2026-10-21",
        "period_end": None,
        "days_left": 3,
        "starts_at": "2026-10-21T04:00:00+00:00",
        "room": "204",
    }
    payload.update(kwargs)
    return payload


def _describe(payload: dict[str, Any], locale: str, i18n: I18nCore) -> Any:
    return describe(
        NotificationType.ASSESSMENT_REMINDER, payload, locale, i18n=i18n, urls=URLS
    )


@pytest.mark.parametrize(
    ("locale", "title", "body"),
    [
        ("en", "Midterm 1 in 3 days: Mathematics", "21.10, 09:00, room 204"),
        (
            "ru",
            "Промежуточный контроль 1 через 3 дня: Mathematics",
            "21.10, 09:00, аудитория 204",
        ),
        (
            "uz",
            "Oraliq nazorat 1 3 kundan keyin: Mathematics",
            "21.10, 09:00, xona 204",
        ),
    ],
)
def test_the_reminder_names_the_control_the_subject_the_day_the_time_and_the_room(
    i18n: I18nCore, locale: str, title: str, body: str
) -> None:
    """Titles in uz, ru and en; the start time is shown in Tashkent time."""
    result = _describe(_payload(), locale, i18n)

    assert (result.title, result.body) == (title, body)


@pytest.mark.parametrize(
    ("days", "en"),
    [(7, "Midterm 1 in 7 days: Mathematics"), (1, "Midterm 1 tomorrow: Mathematics")],
)
def test_the_countdown_is_worded_for_7_and_1_days(
    i18n: I18nCore, days: int, en: str
) -> None:
    """Tomorrow is not "in 1 days"."""
    assert _describe(_payload(days_left=days), "en", i18n).title == en


def test_the_kind_names_a_control_that_has_no_week(i18n: I18nCore) -> None:
    """A final in a plain control falls back to the kind; unknown ones to Control."""
    final = _describe(_payload(control=None, kind="final"), "en", i18n)
    other = _describe(_payload(control=None, kind="other"), "en", i18n)

    assert final.title == "Final exam in 3 days: Mathematics"
    assert other.title == "Control in 3 days: Mathematics"


def test_a_control_week_without_a_date_shows_the_week(i18n: I18nCore) -> None:
    """Subjects nobody dated yet are reminded by the start of the week."""
    result = _describe(
        _payload(
            title="",
            date="2026-10-19",
            period_end="2026-10-24",
            starts_at=None,
            room=None,
            days_left=7,
        ),
        "en",
        i18n,
    )

    assert result.title == "Midterm 1 in 7 days: Mathematics"
    assert result.body == "Control week 19.10 – 24.10"


def test_the_body_leaves_out_a_missing_time_and_room(i18n: I18nCore) -> None:
    """Only the date when nothing else is known."""
    assert _describe(_payload(starts_at=None, room=None), "en", i18n).body == "21.10"


def test_the_link_opens_the_prep_page_of_the_student_app(i18n: I18nCore) -> None:
    """Web push and the bell open /exams/view/?id=."""
    assert _describe(_payload(), "en", i18n).link == f"{URLS.sp}/exams/view/?id={ID}"


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
async def test_the_telegram_message_has_a_button_to_the_prep_page(
    i18n: I18nCore, locale: str
) -> None:
    """Bold title, body and one mini app button."""
    registry = RendererRegistry()
    register_builtin_renderers(
        registry, i18n=i18n, urls=URLS, links=FakeLinksApi(), files=FakeFilesApi()
    )
    renderer = registry.get(NotificationType.ASSESSMENT_REMINDER)
    assert renderer is not None
    ctx = RenderContext(
        user=make_user(Role.STUDENT, locale=locale), locale=locale, telegram_user_id=7
    )

    message = await renderer(_payload(), ctx)

    assert message is not None
    title = _describe(_payload(), locale, i18n).title
    assert message.text_html.startswith(f"<b>{title}</b>\n")
    assert message.buttons is not None
    (button,) = message.buttons[0]
    assert button["web_app_url"] == f"{URLS.sp}/exams/view/?id={ID}"
    assert button["text"] == i18n.t(locale, "notify-btn-open-exam")
