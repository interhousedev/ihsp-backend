"""Small domain helpers: locale negotiation, search queries, the link entity."""

from datetime import UTC, datetime, timedelta

from app.modules.links.domain.lesson_policy import student_window_open
from app.modules.links.domain.link import Link, LinkKind, LinkState
from app.modules.links.domain.locale import pick_locale
from app.modules.links.domain.search_query import extract_slug
from app.shared.ids import new_id

import pytest

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "ru"),
        ("", "ru"),
        ("uz", "uz"),
        ("en-US,en;q=0.9", "en"),
        ("de,fr;q=0.8,uz;q=0.5", "uz"),
        ("en;q=0.1,ru;q=0.9", "ru"),
        ("de", "ru"),
        ("en;q=0", "ru"),
    ],
)
def test_locale_follows_accept_language(header: str | None, expected: str) -> None:
    """SL-4: public pages speak uz, ru or en."""
    assert pick_locale(header) == expected


@pytest.mark.parametrize(
    ("query", "slug"),
    [
        ("7_k", "7_k"),
        ("https://s.ihsu.uz/7_k", "7_k"),
        ("s.ihsu.uz/7_k", "7_k"),
        ("http://localhost:8000/s/7_k", "7_k"),
        ("https://s.ihsu.uz/ai/c-1234", "c-1234"),
        ("https://s.ihsu.uz/7_k?utm=1", "7_k"),
        ("brastilov.aleksey", "brastilov.aleksey"),
    ],
)
def test_moderation_search_reads_slugs_from_urls(query: str, slug: str) -> None:
    """ADM-13: admins can paste a short or share URL."""
    assert extract_slug(query) == slug


def _link(**changes: object) -> Link:
    base = Link(
        id=new_id(),
        slug="7_k",
        kind=LinkKind.URL,
        owner_id=new_id(),
        created_at=NOW,
        target_url="https://example.org/",
    )
    for key, value in changes.items():
        setattr(base, key, value)
    return base


def test_link_state_follows_revocation_expiry_and_disabling() -> None:
    """SL-7: revoked and expired links are gone, disabled ones are disabled."""
    assert _link().state(NOW) is LinkState.ACTIVE
    assert _link(revoked_at=NOW).state(NOW) is LinkState.GONE
    assert _link(expires_at=NOW - timedelta(seconds=1)).state(NOW) is LinkState.GONE
    assert _link(expires_at=NOW + timedelta(days=1)).state(NOW) is LinkState.ACTIVE
    assert _link(disabled_at=NOW).state(NOW) is LinkState.DISABLED
    assert _link(disabled_at=NOW, revoked_at=NOW).state(NOW) is LinkState.GONE


def test_reports_enter_the_queue_until_reviewed_after_the_last_report() -> None:
    """SL-9: queue = reports > 0 and not reviewed since the last report."""
    link = _link()
    assert not link.needs_review

    link.register_report(NOW)
    assert link.needs_review

    link.dismiss_reports(NOW + timedelta(minutes=1))
    assert not link.needs_review

    link.register_report(NOW + timedelta(minutes=2))
    assert link.needs_review
    assert link.reports == 2


def test_disabling_marks_reports_reviewed() -> None:
    """ADM-13: a disabled link leaves the queue."""
    link = _link()
    link.register_report(NOW)

    link.disable(new_id(), "phishing", NOW + timedelta(minutes=1))

    assert link.is_disabled
    assert not link.needs_review


def test_revoking_keeps_the_first_revocation_time() -> None:
    """SL-7: the 90-day clock starts at the first deletion."""
    link = _link()
    link.revoke(NOW)
    link.revoke(NOW + timedelta(days=1))

    assert link.revoked_at == NOW


@pytest.mark.parametrize(
    ("offset_days", "allowed"),
    [(-8, False), (-7, True), (0, True), (14, True), (15, False)],
)
def test_students_attach_from_seven_days_after_to_fourteen_days_ahead(
    offset_days: int, allowed: bool
) -> None:
    """UF-WEB-07 alternative 1a: the attachment window."""
    today = NOW.date()

    assert student_window_open(today + timedelta(days=offset_days), today) is allowed
