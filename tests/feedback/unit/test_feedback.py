"""Feedback use cases on fakes: submit, ownership, limits, attachments, responses."""

from typing import Any

from app.modules.feedback.application.views import FeedbackView
from app.modules.feedback.domain.errors import (
    FeedbackAttachmentError,
    FeedbackInvalidError,
    FeedbackNotFoundError,
    FeedbackRateLimitedError,
)
from app.modules.feedback.domain.feedback import FeedbackSource, FeedbackStatus
from app.shared.base_error import RateLimitedError
from app.shared.ids import new_id
from app.shared.notifications import NotificationType
from tests.feedback.conftest import FeedbackHarness

import pytest


async def submit(fb: FeedbackHarness, **fields: Any) -> FeedbackView:
    values: dict[str, Any] = {
        "kind": "bug",
        "area": "my",
        "title": "  Marks page is blank ",
        "description": "Nothing shows after login.",
    }
    values.update(fields)
    return await fb.services.submit.execute(fb.student, **values)


async def test_submit_stores_the_item_and_tells_the_admins(fb: FeedbackHarness) -> None:
    """FB-01: trimmed fields, status new, source web, one notice per admin."""
    shot = fb.file(fb.student)
    view = await submit(fb, attachment_file_ids=[shot.id, shot.id])

    item = view.item
    assert item.title == "Marks page is blank"
    assert item.status == FeedbackStatus.NEW
    assert item.source == FeedbackSource.WEB
    assert item.attachment_file_ids == [shot.id]
    assert view.attachments[0].download_url.startswith("https://s3.test/")
    [notice] = fb.store.notifications
    assert notice.type == NotificationType.FEEDBACK_NEW
    assert notice.user_id == fb.admin.user_id
    assert notice.payload["title"] == "Marks page is blank"


async def test_the_bot_calls_submit_positionally(fb: FeedbackHarness) -> None:
    """FB-02: submit(actor, kind, area, title, description, files, source=)."""
    view = await fb.services.submit(
        fb.student, "idea", "bot", "Dark mode", "Please", [], source="bot"
    )
    assert view.item.source == FeedbackSource.BOT


@pytest.mark.parametrize(
    ("field", "value"),
    [("kind", "wish"), ("area", "kitchen"), ("title", " "), ("title", "x" * 121),
     ("description", "x" * 4001), ("page_url", "x" * 501)],
)  # fmt: skip
async def test_invalid_fields_are_rejected(
    fb: FeedbackHarness, field: str, value: str
) -> None:
    """FB-01: enums and lengths are validated."""
    with pytest.raises(FeedbackInvalidError) as caught:
        await submit(fb, **{field: value})
    assert caught.value.params["field"] == field


async def test_attachments_must_be_own_ready_and_allowed(fb: FeedbackHarness) -> None:
    """FB-03: foreign, pending, missing, zip and more than 10 files are refused."""
    cases = {
        "not_owner": fb.file(fb.admin).id,
        "not_ready": fb.file(fb.student, status="processing").id,
        "not_found": new_id(),
        "type": fb.file(fb.student, name="a.zip", content_type="application/zip").id,
    }
    for reason, file_id in cases.items():
        with pytest.raises(FeedbackAttachmentError) as caught:
            await submit(fb, attachment_file_ids=[file_id])
        assert caught.value.params["reason"] == reason
    many = [fb.file(fb.student).id for _ in range(11)]
    with pytest.raises(FeedbackAttachmentError):
        await submit(fb, attachment_file_ids=many)
    assert fb.store.items == {}


async def test_eleventh_item_of_the_day_is_rate_limited(fb: FeedbackHarness) -> None:
    """FB-04: 10 per day per user; the error is a 429 with its own code."""
    for _ in range(10):
        await submit(fb)
    with pytest.raises(FeedbackRateLimitedError) as caught:
        await submit(fb)
    assert isinstance(caught.value, RateLimitedError)
    assert caught.value.code == "feedback/rate-limited"
    assert caught.value.status == 429


async def test_only_the_reporter_reads_own_feedback(fb: FeedbackHarness) -> None:
    """FB-06: mine lists own items; someone else's id is not found."""
    view = await submit(fb)
    item_id = view.item.id
    assert [v.item.id for v in await fb.services.list_mine.execute(fb.student)] == [
        item_id
    ]
    assert await fb.services.list_mine.execute(fb.admin) == []
    with pytest.raises(FeedbackNotFoundError):
        await fb.services.get_mine.execute(fb.admin, item_id)


async def test_response_deliveries(fb: FeedbackHarness) -> None:
    """FB-05: telegram queued, mail sent; counted on the item."""
    view = await submit(fb)
    item_id = view.item.id
    fb.store.notifications.clear()
    doc = fb.file(fb.admin, name="fix.pdf", content_type="application/pdf")

    response = await fb.services.respond.execute(
        fb.admin, item_id, text="Fixed", channels=["telegram", "mail"],
        attachment_file_ids=[doc.id],
    )  # fmt: skip

    assert [(d.channel.value, d.status.value) for d in response.deliveries] == [
        ("telegram", "sent"),
        ("mail", "sent"),
    ]
    [notice] = fb.store.notifications
    assert notice.type == NotificationType.FEEDBACK_RESPONSE
    assert notice.user_id == fb.student.user_id
    assert notice.payload["attachments"][0]["name"] == "fix.pdf"
    assert fb.mailer.sent[0]["to"] == "ali.karimov"
    detail = await fb.services.get_mine.execute(fb.student, item_id)
    assert detail.item.response_count == 1
    assert detail.responses[0].author_name


async def test_missing_channels_are_unavailable_and_mail_errors_failed(
    fb: FeedbackHarness,
) -> None:
    """FB-05: no Telegram link or login is unavailable; a mail error is failed."""
    view = await submit(fb)
    item_id = view.item.id
    fb.person(fb.student)  # no login, no Telegram
    fb.store.notifications.clear()
    response = await fb.services.respond.execute(
        fb.admin, item_id, text="Hi", channels=["telegram", "mail"]
    )
    assert {d.status.value for d in response.deliveries} == {"unavailable"}
    assert fb.store.notifications == []

    fb.person(fb.student, login="ali.karimov")
    fb.mailer.fail = True
    failed = await fb.services.respond.execute(
        fb.admin, item_id, text="Hi", channels=["mail"]
    )
    assert failed.deliveries[0].status.value == "failed"


async def test_response_attachments_must_be_the_admins(fb: FeedbackHarness) -> None:
    """FB-05: an admin cannot attach the reporter's files."""
    view = await submit(fb)
    with pytest.raises(FeedbackAttachmentError):
        await fb.services.respond.execute(
            fb.admin,
            view.item.id,
            text="x",
            channels=["mail"],
            attachment_file_ids=[fb.file(fb.student).id],
        )


async def test_admin_list_filters_and_pages(fb: FeedbackHarness) -> None:
    """FB-07: filters, newest first, cursor to the next page; status changes."""
    first = await submit(fb, kind="idea")
    await submit(fb)
    await submit(fb)
    page = await fb.services.list_all.execute(kind=None, limit=2)
    assert len(page.items) == 2 and page.next_cursor
    rest = await fb.services.list_all.execute(cursor=page.next_cursor, limit=2)
    assert [v.item.id for v in rest.items] == [first.item.id]
    assert rest.next_cursor is None
    ideas = await fb.services.list_all.execute(kind="idea")
    assert [v.item.id for v in ideas.items] == [first.item.id]
    assert ideas.items[0].reporter is not None

    detail = await fb.services.set_status.execute(first.item.id, "planned")
    assert detail.item.status == FeedbackStatus.PLANNED
    assert detail.reporter is not None and detail.reporter.group_name == "2TN2"
    with pytest.raises(FeedbackInvalidError):
        await fb.services.set_status.execute(first.item.id, "closed")
    with pytest.raises(FeedbackInvalidError):
        await fb.services.list_all.execute(cursor="%%%")
