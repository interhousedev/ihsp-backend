"""Personal plan entries: draft checks, safe links, dedup keys, HTTP schemas."""

import datetime as dt

from app.interfaces.http.v1.admission.schemas_opportunities import (
    PersonalCreateIn,
    PersonalUpdateIn,
)
from app.modules.admission.domain.personal_entries import (
    PersonalDraft,
    dedup_key,
    is_safe_url,
)
from app.modules.notify.application.renderers.admission_deadline_reminder import (
    AdmissionDeadlineReminderRenderer,
)
from app.settings import UrlsSettings
from app.shared.actor import Role
from app.shared.contracts.notify import RenderContext
from app.shared.i18n.core import I18nCore
from app.shared.paths import LOCALES_DIR
from tests.bot.support.fakes import make_user

import pytest
from pydantic import ValidationError


def test_valid_draft_has_no_problems() -> None:
    draft = PersonalDraft(
        kind="event",
        title="Summer school",
        provider="MIT",
        url="https://example.org/summer",
        starts_on=dt.date(2027, 7, 5),
        ends_on=dt.date(2027, 7, 19),
        planned_term="summer",
    )
    assert draft.problems() == []


def test_draft_problems_name_the_fields() -> None:
    draft = PersonalDraft(
        kind="party",
        title="  ",
        url="http://example.org",
        starts_on=dt.date(2027, 7, 19),
        ends_on=dt.date(2027, 7, 5),
        planned_term="winter",
    )
    assert draft.problems() == ["kind", "title", "url", "ends_on", "planned_term"]
    far = PersonalDraft(kind="event", title="x", starts_on=dt.date(1999, 1, 1))
    assert far.problems() == ["dates"]
    control = PersonalDraft(kind="event", title="a\u202eb")
    assert control.problems() == ["title"]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/a?b=1",
        "https://xn--80ak6aa92e.xn--p1ai/",
        "https://example.org:443/",
    ],
)
def test_safe_urls(url: str) -> None:
    assert is_safe_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org",
        "javascript:alert(1)",
        "https://user:pw@example.org/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://localhost/",
        "https://example.org:8443/",
        "https://example.org/<script>",
        "https://example.org/a b",
        "",
    ],
)
def test_unsafe_urls(url: str) -> None:
    assert not is_safe_url(url)


def test_dedup_key_is_order_free() -> None:
    assert dedup_key(["a", "b"]) == dedup_key(["b", "a", "a"])
    assert len(dedup_key(["a"])) == 64
    assert dedup_key(["a"]) != dedup_key(["b"])


def test_create_and_update_bodies_map_to_drafts() -> None:
    body = PersonalCreateIn.model_validate(
        {"kind": "course", "title": "Stats", "propose": True, "planned_grade": 10}
    )
    assert body.propose is True
    assert body.draft() == PersonalDraft(kind="course", title="Stats", planned_grade=10)
    upd = PersonalUpdateIn.model_validate(
        {"kind": "course", "title": "Stats", "lock_version": 2}
    )
    assert upd.draft() == PersonalDraft(kind="course", title="Stats")
    with pytest.raises(ValidationError):
        PersonalCreateIn.model_validate({"kind": "course", "title": "x" * 201})
    with pytest.raises(ValidationError):
        PersonalUpdateIn.model_validate({"kind": "course", "title": "x"})


async def test_calendar_reminder_escapes_the_student_title() -> None:
    """The title of an own find is student or AI text: it must not become HTML."""
    renderer = AdmissionDeadlineReminderRenderer(
        I18nCore(LOCALES_DIR).load(), UrlsSettings()
    )
    message = await renderer(
        {
            "source": "personal",
            "title": '<a href="https://evil.example">win</a> & <b>',
            "title_key": None,
            "days": 3,
            "due_utc": "2027-03-12T18:59:59+00:00",
        },
        RenderContext(user=make_user(Role.STUDENT), locale="en", telegram_user_id=1),
    )
    assert message is not None
    assert "<a href" not in message.text_html
    assert "&lt;a href=" in message.text_html and "&amp;" in message.text_html
