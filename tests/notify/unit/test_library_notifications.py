"""LIB-5: the library notifications: web text, links and the Telegram renderers."""

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
ITEM_ID = str(new_id())
LIST_ID = str(new_id())

LIBRARY_TYPES = [
    NotificationType.LIBRARY_ITEM_APPROVED,
    NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED,
    NotificationType.LIBRARY_ITEM_REJECTED,
    NotificationType.LIBRARY_ITEM_UNPUBLISHED,
    NotificationType.LIBRARY_QUEUE_WAITING,
    NotificationType.LIBRARY_REPORT_FILED,
    NotificationType.LIBRARY_READING_LIST_NEW,
]

PAYLOADS: dict[NotificationType, dict[str, Any]] = {
    NotificationType.LIBRARY_ITEM_APPROVED: {"item_id": ITEM_ID, "title": "Algebra"},
    NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED: {
        "item_id": ITEM_ID,
        "title": "Algebra",
        "message": "Scan the pages straight.",
    },
    NotificationType.LIBRARY_ITEM_REJECTED: {
        "item_id": ITEM_ID,
        "title": "Algebra",
        "reason": "duplicate",
        "message": "It is already in the library.",
    },
    NotificationType.LIBRARY_ITEM_UNPUBLISHED: {
        "item_id": ITEM_ID,
        "title": "Algebra",
        "reason": "copyright",
        "note": "The publisher asked us.",
    },
    NotificationType.LIBRARY_QUEUE_WAITING: {"count": 7, "oldest_hours": 52},
    NotificationType.LIBRARY_REPORT_FILED: {
        "item_id": ITEM_ID,
        "title": "Algebra",
        "reason": "exam_leak",
    },
    NotificationType.LIBRARY_READING_LIST_NEW: {
        "list_id": LIST_ID,
        "title": "Start of term",
        "subject": "Physics",
    },
}


def _describe(
    kind: NotificationType, locale: str, i18n: I18nCore, **changes: Any
) -> Any:
    payload = {**PAYLOADS[kind], **changes}
    return describe(kind, payload, locale, i18n=i18n, urls=URLS)


def test_the_library_notification_types_have_their_stored_names() -> None:
    """LIB-5: the values written to `notify.notifications.type`."""
    assert [kind.value for kind in LIBRARY_TYPES] == [
        "library_item_approved",
        "library_item_changes_requested",
        "library_item_rejected",
        "library_item_unpublished",
        "library_queue_waiting",
        "library_report_filed",
        "library_reading_list_new",
    ]


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
@pytest.mark.parametrize("kind", LIBRARY_TYPES)
def test_every_library_type_reads_in_every_language_without_raw_keys(
    i18n: I18nCore, kind: NotificationType, locale: str
) -> None:
    """LIB-5: a title and a body, no `notify-` key leaks to the bell."""
    result = _describe(kind, locale, i18n)

    assert result.title
    assert result.body
    assert "notify-" not in result.title + result.body


@pytest.mark.parametrize(
    ("locale", "title", "body"),
    [
        (
            "en",
            "Material published",
            "“Algebra” passed review and is now in the library.",
        ),
        (
            "ru",
            "Материал опубликован",
            "«Algebra» прошёл проверку и теперь в библиотеке.",
        ),
        (
            "uz",
            "Material e'lon qilindi",
            "«Algebra» tekshiruvdan o'tdi va endi kutubxonada.",
        ),
    ],
)
def test_an_approved_material_is_announced_to_its_author(
    i18n: I18nCore, locale: str, title: str, body: str
) -> None:
    """LIB-5: approved shows the title of the item."""
    result = _describe(NotificationType.LIBRARY_ITEM_APPROVED, locale, i18n)

    assert (result.title, result.body) == (title, body)


def test_changes_requested_carries_the_librarians_message(i18n: I18nCore) -> None:
    """LIB-5: the author sees what to fix; without a message there is no colon."""
    with_message = _describe(
        NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED, "en", i18n
    )
    without = _describe(
        NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED, "en", i18n, message=None
    )

    assert with_message.title == "Changes requested"
    assert with_message.body == (
        "A librarian asks you to change “Algebra”: Scan the pages straight."
    )
    assert without.body == "A librarian asks you to change “Algebra”."


def test_a_rejection_names_the_reason_and_adds_the_message(i18n: I18nCore) -> None:
    """LIB-5, LIB-14: a known reason code is shown as words, the message follows."""
    result = _describe(NotificationType.LIBRARY_ITEM_REJECTED, "en", i18n)

    assert result.title == "Material rejected"
    assert result.body == (
        "“Algebra” was rejected. Reason: duplicate. It is already in the library."
    )


def test_a_rejection_in_russian_translates_the_reason_code(i18n: I18nCore) -> None:
    """LIB-5: the reason code is looked up per language."""
    result = _describe(NotificationType.LIBRARY_ITEM_REJECTED, "ru", i18n)

    assert result.body.startswith("«Algebra» отклонён. Причина: дубликат.")


def test_an_unknown_reason_code_is_shown_as_it_is(i18n: I18nCore) -> None:
    """LIB-5: a new code never breaks the text."""
    result = _describe(
        NotificationType.LIBRARY_ITEM_REJECTED,
        "en",
        i18n,
        reason="new_reason_code",
        message=None,
    )

    assert result.body == "“Algebra” was rejected. Reason: new_reason_code."


def test_a_rejection_without_reason_or_message_is_one_sentence(
    i18n: I18nCore,
) -> None:
    """LIB-5: every payload field but item_id and title is optional."""
    result = _describe(
        NotificationType.LIBRARY_ITEM_REJECTED, "en", i18n, reason=None, message=None
    )

    assert result.body == "“Algebra” was rejected."


def test_an_unpublished_item_shows_the_reason_and_the_note(i18n: I18nCore) -> None:
    """LIB-5, LIB-14: the owner of a taken-down item is told why."""
    result = _describe(NotificationType.LIBRARY_ITEM_UNPUBLISHED, "en", i18n)

    assert result.title == "Removed from the library"
    assert result.body == (
        "“Algebra” was removed from the library. Reason: copyright. "
        "The publisher asked us."
    )


def test_the_queue_reminder_gives_the_count_and_the_oldest_wait(
    i18n: I18nCore,
) -> None:
    """LIB-5: sent to librarians when items wait more than 2 school days."""
    result = _describe(NotificationType.LIBRARY_QUEUE_WAITING, "en", i18n)
    no_age = _describe(
        NotificationType.LIBRARY_QUEUE_WAITING, "en", i18n, oldest_hours=None
    )

    assert result.title == "Materials are waiting for review"
    assert result.body == "In the queue: 7. The oldest has waited 52 h."
    assert no_age.body == "In the queue: 7."


def test_a_report_names_the_item_and_the_reason_but_not_the_reporter(
    i18n: I18nCore,
) -> None:
    """LIB-5, LIB-14: the librarians see what was reported and why."""
    result = _describe(NotificationType.LIBRARY_REPORT_FILED, "en", i18n)

    assert result.title == "New report"
    assert result.body == (
        "“Algebra” was reported: material of a control that has not finished."
    )


def test_a_new_reading_list_names_its_subject_when_it_has_one(i18n: I18nCore) -> None:
    """LIB-4, LIB-5: students are told about a list for their subject."""
    result = _describe(NotificationType.LIBRARY_READING_LIST_NEW, "en", i18n)
    no_subject = _describe(
        NotificationType.LIBRARY_READING_LIST_NEW, "en", i18n, subject=None
    )

    assert result.title == "New reading list"
    assert result.body == "Reading list “Start of term” for Physics."
    assert no_subject.body == "Reading list “Start of term” was added."


@pytest.mark.parametrize(
    ("kind", "link"),
    [
        (NotificationType.LIBRARY_ITEM_APPROVED, f"/item/?id={ITEM_ID}"),
        (NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED, f"/item/?id={ITEM_ID}"),
        (NotificationType.LIBRARY_ITEM_REJECTED, f"/item/?id={ITEM_ID}"),
        (NotificationType.LIBRARY_ITEM_UNPUBLISHED, f"/item/?id={ITEM_ID}"),
        (NotificationType.LIBRARY_QUEUE_WAITING, "/manage/queue/"),
        (NotificationType.LIBRARY_REPORT_FILED, "/manage/queue/"),
        (NotificationType.LIBRARY_READING_LIST_NEW, f"/lists/view/?id={LIST_ID}"),
    ],
)
def test_links_open_the_library_app(
    i18n: I18nCore, kind: NotificationType, link: str
) -> None:
    """LIB-5: entities by query parameter on the library origin."""
    assert _describe(kind, "en", i18n).link == f"{URLS.library}{link}"


def test_the_library_origin_comes_from_the_urls_settings(i18n: I18nCore) -> None:
    """LIB-5: in production the links start with https://lib.ihsu.uz."""
    urls = UrlsSettings(library="https://lib.ihsu.uz")

    result = describe(
        NotificationType.LIBRARY_ITEM_APPROVED,
        PAYLOADS[NotificationType.LIBRARY_ITEM_APPROVED],
        "uz",
        i18n=i18n,
        urls=urls,
    )

    assert result.link == f"https://lib.ihsu.uz/item/?id={ITEM_ID}"


def _registry(i18n: I18nCore) -> RendererRegistry:
    registry = RendererRegistry()
    register_builtin_renderers(
        registry, i18n=i18n, urls=URLS, links=FakeLinksApi(), files=FakeFilesApi()
    )
    return registry


@pytest.mark.parametrize("kind", LIBRARY_TYPES)
def test_every_library_type_has_a_telegram_renderer(
    i18n: I18nCore, kind: NotificationType
) -> None:
    """LIB-5, BOT-11: the notify module renders them, not the bot module."""
    assert _registry(i18n).get(kind) is not None


@pytest.mark.parametrize("locale", ["en", "ru", "uz"])
@pytest.mark.parametrize(
    ("kind", "role", "button_key", "path"),
    [
        (
            NotificationType.LIBRARY_ITEM_APPROVED,
            Role.STUDENT,
            "notify-btn-open-library-item",
            f"/item/?id={ITEM_ID}",
        ),
        (
            NotificationType.LIBRARY_ITEM_REJECTED,
            Role.STUDENT,
            "notify-btn-open-library-item",
            f"/item/?id={ITEM_ID}",
        ),
        (
            NotificationType.LIBRARY_QUEUE_WAITING,
            Role.LIBRARIAN,
            "notify-btn-open-library-queue",
            "/manage/queue/",
        ),
        (
            NotificationType.LIBRARY_REPORT_FILED,
            Role.LIBRARIAN,
            "notify-btn-open-library-queue",
            "/manage/queue/",
        ),
        (
            NotificationType.LIBRARY_READING_LIST_NEW,
            Role.STUDENT,
            "notify-btn-open-library-list",
            f"/lists/view/?id={LIST_ID}",
        ),
    ],
)
async def test_the_telegram_message_has_a_link_button_to_the_library(
    i18n: I18nCore,
    locale: str,
    kind: NotificationType,
    role: Role,
    button_key: str,
    path: str,
) -> None:
    """LIB-5: bold title, body and one plain URL button (the library is no mini app)."""
    renderer = _registry(i18n).get(kind)
    assert renderer is not None
    ctx = RenderContext(
        user=make_user(role, locale=locale), locale=locale, telegram_user_id=7
    )

    message = await renderer(PAYLOADS[kind], ctx)

    assert message is not None
    title = _describe(kind, locale, i18n).title
    assert message.text_html.startswith(f"<b>{title}</b>\n")
    assert message.buttons is not None
    (button,) = message.buttons[0]
    assert button == {
        "text": i18n.t(locale, button_key),
        "url": f"{URLS.library}{path}",
    }
    assert "notify-" not in button["text"]


async def test_the_librarians_message_is_escaped_for_telegram(i18n: I18nCore) -> None:
    """LIB-5: markup in a title or message does not reach Telegram as HTML."""
    renderer = _registry(i18n).get(NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED)
    assert renderer is not None
    ctx = RenderContext(
        user=make_user(Role.STUDENT, locale="en"), locale="en", telegram_user_id=7
    )
    payload = {**PAYLOADS[NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED]}
    payload["message"] = "<b>fix</b> & resend"

    message = await renderer(payload, ctx)

    assert message is not None
    assert "&lt;b&gt;fix&lt;/b&gt; &amp; resend" in message.text_html
