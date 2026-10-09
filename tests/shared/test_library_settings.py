"""LIB-1: the `LIBRARY__*` settings of the library (doc 8.2)."""

from app.settings import LibrarySettings, Settings

import pytest


def test_library_limits_default_to_the_values_of_the_spec() -> None:
    """LIB-1: sizes, quotas, limits and the queue service level."""
    library = Settings().library

    assert library.file_max_bytes == 300 * 1024 * 1024
    assert library.material_student_max_bytes == 20 * 1024 * 1024
    assert library.material_student_max_pages == 60
    assert library.material_teacher_max_bytes == 100 * 1024 * 1024
    assert library.student_quota_bytes == 300 * 1024 * 1024
    assert library.teacher_quota_bytes == 2 * 1024 * 1024 * 1024
    assert library.reader_url_seconds == 900
    assert library.teacher_review is False
    assert library.list_max_items == 100
    assert library.limit_uploads_day_student == 10
    assert library.limit_uploads_week_student == 40
    assert library.limit_uploads_day_teacher == 30
    assert library.limit_reports_day == 10
    assert library.auto_hold_reporters == 2
    assert library.queue_sla_school_days == 2
    assert library.offline_max_items == 5
    assert library.offline_max_bytes == 400 * 1024 * 1024


def test_unilibrary_is_off_and_asks_politely_by_default() -> None:
    """LIB-1: the switched-off base: flag off, 3 requests a second, 2 at a time."""
    library = Settings().library

    assert library.unilibrary_enabled is False
    assert library.unilibrary_anonymous_cards is False
    assert library.unilibrary_base_url == "https://api.unilibrary.uz"
    assert library.unilibrary_rps == 3
    assert library.unilibrary_concurrency == 2
    assert library.unilibrary_list_timeout == 8
    assert library.unilibrary_detail_timeout == 5
    assert library.unilibrary_cache_list_ttl == 600
    assert library.unilibrary_cache_detail_ttl == 86400
    assert library.unilibrary_stale_ttl == 604800
    assert library.unilibrary_breaker_failures == 3
    assert library.unilibrary_breaker_seconds == 60
    assert library.unilibrary_user_searches_per_min == 30
    assert library.unilibrary_description_max == 600
    assert library.unilibrary_contact == ""


def test_public_links_and_the_taxonomy_cache_have_defaults() -> None:
    """LIB-1: notifications link to the library host; topics are cached a week."""
    library = Settings().library

    assert library.public_base_url == "https://library.ihsu.uz"
    assert library.taxonomy_cache_ttl == 604800


def test_library_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LIB-1: `IHSP_LIBRARY__*` reaches `settings.library`."""
    monkeypatch.setenv("IHSP_LIBRARY__TEACHER_REVIEW", "true")
    monkeypatch.setenv("IHSP_LIBRARY__STUDENT_QUOTA_BYTES", "1000")
    monkeypatch.setenv("IHSP_LIBRARY__UNILIBRARY_ENABLED", "true")
    monkeypatch.setenv("IHSP_LIBRARY__UNILIBRARY_RPS", "0.5")

    library = Settings().library

    assert library.teacher_review is True
    assert library.student_quota_bytes == 1000
    assert library.unilibrary_enabled is True
    assert library.unilibrary_rps == 0.5


def test_the_user_agent_is_ours_and_gains_the_contact_when_one_is_set() -> None:
    """LIB-1: honest requests, with a contact for the other side when we know it."""
    assert LibrarySettings().unilibrary_agent() == "IHSP-library/1.0 (+https://ihsu.uz)"

    with_contact = LibrarySettings(unilibrary_contact="admin@ihsu.uz")

    assert with_contact.unilibrary_agent() == (
        "IHSP-library/1.0 (+https://ihsu.uz; contact: admin@ihsu.uz)"
    )


def test_a_custom_user_agent_without_parentheses_gets_the_contact_appended() -> None:
    """LIB-1: the contact is added whatever the base string looks like."""
    library = LibrarySettings(unilibrary_user_agent="Bot/2", unilibrary_contact="a@b.c")

    assert library.unilibrary_agent() == "Bot/2 (contact: a@b.c)"


def test_the_features_flag_of_the_library_is_on_by_default() -> None:
    """LIB-1: `FEATURES__LIBRARY` now switches the library routes and jobs."""
    assert Settings().features.library is True
