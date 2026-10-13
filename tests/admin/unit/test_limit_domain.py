"""The runtime limits catalogue, value checks and extension terms (no database)."""

from datetime import date

from app.modules.admin.domain.limits import (
    ExtensionTerms,
    LimitExtensionInvalidError,
    LimitInvalidError,
    check_extension,
    check_value,
    editable_specs,
    is_hidden,
    overrides_from_rows,
    spec_of,
)
from app.settings import LimitsSettings
from app.shared.limits import LIMIT_PREFIXES

import pytest

TODAY = date(2026, 10, 11)
KEYS = {spec.key for spec in editable_specs()}


def test_the_catalogue_follows_the_settings_class_by_prefix() -> None:
    assert KEYS
    assert all(key.startswith(LIMIT_PREFIXES) for key in KEYS)
    assert {
        "ai_daily_tokens_student",
        "nb_chat_per_minute",
        "web_search_deep_results",
    } <= KEYS
    assert "ai_smart_requests_per_week_student" in KEYS  # added by the smart tier


def test_staff_only_quotas_and_the_deprecated_alias_are_not_editable() -> None:
    assert "lms_ai_session_tokens" not in KEYS
    assert "lms_ai_artifacts_per_day" not in KEYS
    assert "web_search_per_day_staff" not in KEYS
    assert "ai_smart_requests_per_week_staff" not in KEYS
    assert "ai_smart_weight" not in KEYS
    assert is_hidden("lms_ai_daily_tokens") and not is_hidden("lms_ai_chat_per_minute")


def test_groups_units_and_periods_are_derived_from_the_names() -> None:
    assert spec_of("ai_daily_tokens_student").group == "assistant"
    assert spec_of("ai_daily_tokens_student").unit == "tokens"
    assert spec_of("ai_daily_tokens_student").period == "day"
    assert spec_of("ai_smart_requests_per_week_student").group == "smart"
    assert spec_of("ai_smart_requests_per_week_student").period == "week"
    assert spec_of("nb_slides_per_day").group == "notebooks"
    assert spec_of("web_search_per_day_student").group == "web_search"
    assert spec_of("lms_ai_chat_per_minute").group == "lms"
    assert spec_of("ai_session_hours").unit == "hours"
    assert spec_of("ai_text_max_bytes").unit == "bytes"
    assert spec_of("ai_max_tool_steps").unit == "steps"


def test_the_bounds_come_from_the_field_constraints_and_the_unit() -> None:
    assert spec_of("ai_session_hours").minimum == 1
    assert spec_of("web_search_max_results").maximum == 10
    assert spec_of("ai_daily_tokens_student").maximum == 1_000_000_000


def test_a_value_must_be_a_whole_number_within_its_bounds() -> None:
    spec = spec_of("ai_session_hours")

    assert check_value(spec, None) is None
    assert check_value(spec, 24) == 24
    for bad in (0, -1, 10_000, True, 2.5, "7"):
        with pytest.raises(LimitInvalidError):
            check_value(spec, bad)


def test_an_unknown_or_hidden_key_is_refused() -> None:
    with pytest.raises(LimitInvalidError):
        spec_of("mail_per_day")
    with pytest.raises(LimitInvalidError):
        spec_of("lms_ai_session_tokens")


def test_stored_rows_keep_only_valid_overrides() -> None:
    rows = {
        "limit.nb_chat_per_minute": 20,
        "limit.lms_ai_session_tokens": 5,
        "limit.nb_slides_per_day": "many",
        "limit.not_a_limit": 1,
        "other.key": 3,
    }

    assert overrides_from_rows(rows) == {"nb_chat_per_minute": 20}


def test_the_environment_default_is_the_base_of_every_catalogue_entry() -> None:
    assert LimitsSettings().nb_chat_per_minute == 10


def test_extension_terms_need_a_grant_in_range() -> None:
    with pytest.raises(LimitExtensionInvalidError):
        check_extension(ExtensionTerms(), TODAY)
    with pytest.raises(LimitExtensionInvalidError):
        check_extension(ExtensionTerms(multiplier=1), TODAY)
    with pytest.raises(LimitExtensionInvalidError):
        check_extension(ExtensionTerms(multiplier=11), TODAY)
    with pytest.raises(LimitExtensionInvalidError):
        check_extension(ExtensionTerms(values={"lms_ai_session_tokens": 10}), TODAY)
    with pytest.raises(LimitExtensionInvalidError):
        check_extension(
            ExtensionTerms(multiplier=2, expires_on=date(2026, 10, 10)), TODAY
        )
    with pytest.raises(LimitExtensionInvalidError):
        check_extension(ExtensionTerms(multiplier=2, note="x" * 501), TODAY)


def test_valid_extension_terms_are_kept_with_a_trimmed_note() -> None:
    checked = check_extension(
        ExtensionTerms(
            multiplier=5,
            values={"nb_chat_per_minute": 30},
            expires_on=TODAY,
            note="  thesis  ",
        ),
        TODAY,
    )

    assert checked.multiplier == 5
    assert checked.values == {"nb_chat_per_minute": 30}
    assert checked.note == "thesis"


def test_the_chat_history_limit_is_editable_in_its_bounds() -> None:
    """AI-EFF-3: Administration changes the history limit at runtime (2..200)."""
    spec = spec_of("ai_chat_history_limit")

    assert (spec.group, spec.unit) == ("assistant", "count")
    assert (spec.minimum, spec.maximum) == (2, 200)
