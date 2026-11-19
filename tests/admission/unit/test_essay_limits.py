"""Essay reviewer limits: runtime-editable, grouped, and read at call time."""

from app.modules.admin.domain.limits import check_value, editable_specs, spec_of
from app.modules.admission.domain.prompt_studio import SampleInput
from app.settings import LimitsSettings
from app.shared.actor import Role
from app.shared.base_error import RateLimitedError
from app.shared.limits import ActorLimits, LimitExtension, apply_extension
from tests.admission.unit.fakes_prompt_studio import Studio
from tests.admission.unit.test_access_policy import STAFF, World, _assign

import pytest

KEYS = (
    "admit_essay_review_per_week",
    "admit_essay_uni_review_per_week",
    "admit_essay_studio_runs_per_day",
)
SAMPLE = SampleInput(text="My essay text.")


def test_the_three_limits_are_editable_in_the_essay_group() -> None:
    """ADM-Q-001 base, per-university and studio limits form the essay group."""
    listed = {s.key for s in editable_specs() if s.group == "essay"}

    assert listed == set(KEYS)
    assert spec_of("admit_essay_studio_runs_per_day").period == "day"
    assert spec_of("admit_essay_review_per_week").period == "week"
    assert spec_of("admit_essay_coach_per_day").group == "admission"


def test_defaults_and_minus_one_are_valid() -> None:
    """ADM-Q-002 defaults are 10, 30 and 30; -1 (no cap) is accepted."""
    limits = LimitsSettings()

    assert limits.admit_essay_review_per_week == 10
    assert limits.admit_essay_uni_review_per_week == 30
    assert limits.admit_essay_studio_runs_per_day == 30
    for key in KEYS:
        assert check_value(spec_of(key), -1) == -1


def test_extension_raises_the_per_user_review_limit() -> None:
    """ADM-Q-003 a per-user multiplier raises the review limits, never lowers."""
    base = LimitsSettings()

    grown = apply_extension(base, LimitExtension(multiplier=3, values={}))

    assert grown.admit_essay_review_per_week == 30
    assert grown.admit_essay_uni_review_per_week == 90
    off = LimitsSettings(admit_essay_review_per_week=-1)
    limits = ActorLimits(off, unlimited=False)
    assert limits.admit_essay_review_per_week is None


async def test_studio_reads_the_runtime_limit_on_every_call() -> None:
    """ADM-Q-004 a lowered studio limit applies to the next run; None is no cap."""
    w = World()
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    s = Studio(w.store)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    cap: int | None = 1

    async def per_day() -> int | None:
        return cap

    s.service._per_day = per_day
    await s.service.test(
        ctx, "admit_essay_review", "base", text="d", samples=[SAMPLE], locale="en"
    )
    with pytest.raises(RateLimitedError):
        await s.service.test(
            ctx, "admit_essay_review", "base", text="d", samples=[SAMPLE], locale="en"
        )
    cap = None
    for _ in range(3):
        await s.service.test(
            ctx, "admit_essay_review", "base", text="d", samples=[SAMPLE], locale="en"
        )
