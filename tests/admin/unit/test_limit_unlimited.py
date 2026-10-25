"""-1 (no cap) is valid only for the allow-listed quotas; readers see None for it."""

from app.modules.admin.domain.limits import (
    LimitInvalidError,
    check_value,
    editable_specs,
    spec_of,
)
from app.settings import LimitsSettings
from app.shared.limits import (
    UNLIMITABLE,
    UNLIMITED,
    ActorLimits,
    LimitExtension,
    apply_extension,
    apply_overrides,
)

import pytest


def test_the_allow_list_is_flagged_in_the_catalogue_and_nothing_else() -> None:
    flagged = {spec.key for spec in editable_specs() if spec.unlimitable}

    assert flagged == set(UNLIMITABLE)
    assert spec_of("ai_daily_tokens_student").unlimitable
    assert spec_of("ai_smart_requests_per_week_student").unlimitable
    assert spec_of("web_search_per_day_student").unlimitable
    assert not spec_of("ai_chat_history_limit").unlimitable
    assert not spec_of("ai_session_hours").unlimitable


def test_minus_one_is_accepted_only_for_allow_listed_limits() -> None:
    assert check_value(spec_of("ai_daily_tokens_student"), UNLIMITED) == -1
    assert check_value(spec_of("nb_artifacts_per_day"), -1) == -1
    assert check_value(spec_of("web_search_per_day_student"), 0) == 0

    for name in ("ai_session_hours", "ai_max_tool_steps", "nb_chat_per_minute"):
        with pytest.raises(LimitInvalidError):
            check_value(spec_of(name), -1)
    with pytest.raises(LimitInvalidError):
        check_value(spec_of("ai_daily_tokens_student"), -2)
    with pytest.raises(LimitInvalidError):
        check_value(spec_of("ai_daily_tokens_student"), True)


def test_the_environment_accepts_minus_one_for_the_allow_listed_limits() -> None:
    limits = LimitsSettings(ai_daily_tokens_student=-1)

    assert limits.ai_daily_tokens_student == -1


def test_actor_limits_read_minus_one_as_no_cap_for_allow_listed_only() -> None:
    base = apply_overrides(
        LimitsSettings(),
        {"ai_daily_tokens_student": -1, "nb_chat_per_minute": 4},
    )
    view = ActorLimits(base, unlimited=False)

    assert view.ai_daily_tokens_student is None
    assert view.nb_chat_per_minute == 4


def test_an_extension_keeps_minus_one_through_multiplier_and_values() -> None:
    base = LimitsSettings(ai_daily_tokens_student=-1, nb_daily_tokens_student=100)
    extended = apply_extension(
        base,
        LimitExtension(
            multiplier=4,
            values={"ai_daily_tokens_student": 9_000, "nb_daily_tokens_student": 500},
        ),
    )

    assert extended.ai_daily_tokens_student == UNLIMITED
    assert extended.nb_daily_tokens_student == 500


def test_an_extension_granting_no_cap_lifts_a_finite_limit() -> None:
    base = LimitsSettings(ai_daily_tokens_student=100)
    lifted = apply_extension(
        base, LimitExtension(values={"ai_daily_tokens_student": UNLIMITED})
    )

    assert lifted.ai_daily_tokens_student == UNLIMITED
    assert check_value(spec_of("ai_daily_tokens_student"), UNLIMITED) == UNLIMITED
