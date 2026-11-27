"""Level schemes, pure domain (spec 2.5).

The implementation must provide `app.modules.lms.domain.engagement.levels`:
  Curve.quadratic(base=50) / Curve.table([xp_for_level_2, xp_for_level_3, ...])
    .xp_to_reach(level) -> int (level 1 == 0)
  LevelTier(level_from, title{uz,ru,en}, icon, color, reward_badge_id=None)
  LevelScheme(id, scope 'platform'|'course', course_id, name, curve, tiers, active)
    .validate() raises LevelSchemeInvalidError(params.field)
    .tier_of(level) -> LevelTier | None
  level_of(xp, scheme) -> app.modules.lms.domain.engagement.xp.Level
  DEFAULT_SCHEME: quadratic base 50, one tier from level 1
  apply_xp(highest_level, xp, scheme) -> (level_shown, new_highest, leveled_up: bool)
  distribution(xps, scheme) -> dict[int, int]   (level -> learners)
Boring choices: table curve lists cumulative XP to reach levels 2..N and the level
is capped at N+1; tiers must start at level 1, be sorted and contiguous (each
level_from is the previous tier's end + 1, the last tier is open-ended);
level_shown never drops below the stored highest_level.
"""

from uuid import uuid4

from app.modules.lms.domain.engagement import xp as legacy
from app.modules.lms.domain.engagement.levels import (
    DEFAULT_SCHEME,
    Curve,
    LevelScheme,
    LevelSchemeInvalidError,
    LevelTier,
    apply_xp,
    distribution,
    level_of,
)

import pytest

T = {"uz": "x", "ru": "x", "en": "x"}


def tier(start: int) -> LevelTier:
    return LevelTier(level_from=start, title=T, icon="star", color="#336699")


def scheme(curve: Curve, *tiers: LevelTier, **kw: object) -> LevelScheme:
    return LevelScheme(
        id=uuid4(),
        scope=kw.get("scope", "platform"),  # type: ignore[arg-type]
        course_id=kw.get("course_id"),  # type: ignore[arg-type]
        name=T,
        curve=curve,
        tiers=list(tiers) or [tier(1)],
        active=False,
    )


@pytest.mark.parametrize("xp", [0, 1, 99, 100, 299, 300, 350, 599, 600, 12_345, 10**6])
def test_default_scheme_reproduces_the_legacy_curve(xp: int) -> None:
    """Parity with xp.py: the seeded scheme must not change anyone's level."""
    assert level_of(xp, DEFAULT_SCHEME) == legacy.level_of(xp)


def test_quadratic_curve_matches_formula() -> None:
    c = Curve.quadratic(base=50)
    assert [c.xp_to_reach(n) for n in (1, 2, 3, 4)] == [0, 100, 300, 600]


def test_table_curve() -> None:
    s = scheme(Curve.table([100, 250, 500]))
    assert level_of(0, s).level == 1
    assert level_of(100, s).level == 2
    assert level_of(249, s).level == 2
    lv = level_of(260, s)
    assert (lv.level, lv.xp_into_level, lv.xp_for_next) == (3, 10, 250)
    assert level_of(10**6, s).level == 4  # capped at the table's last level


@pytest.mark.parametrize("table", [[], [100, 100], [100, 50], [0, 10], [-5, 10]])
def test_curve_must_be_strictly_increasing_and_positive(table: list[int]) -> None:
    with pytest.raises(LevelSchemeInvalidError):
        scheme(Curve.table(table)).validate()


def test_quadratic_base_must_be_positive() -> None:
    with pytest.raises(LevelSchemeInvalidError):
        scheme(Curve.quadratic(base=0)).validate()


def test_valid_contiguous_tiers_pass() -> None:
    scheme(Curve.quadratic(50), tier(1), tier(5), tier(10)).validate()


@pytest.mark.parametrize(
    "starts",
    [[2, 5], [1, 1], [1, 5, 4], [3, 1], []],
    ids=["gap-at-start", "overlap", "unsorted-tail", "unsorted", "empty"],
)
def test_tiers_must_start_at_1_and_be_strictly_ascending(starts: list[int]) -> None:
    s = scheme(Curve.quadratic(50))
    s.tiers = [tier(n) for n in starts]
    with pytest.raises(LevelSchemeInvalidError):
        s.validate()


def test_tier_of_picks_the_covering_tier() -> None:
    s = scheme(Curve.quadratic(50), tier(1), tier(5), tier(10))
    assert [s.tier_of(n).level_from for n in (1, 4, 5, 9, 10, 99)] == [
        1,
        1,
        5,
        5,
        10,
        10,
    ]


def test_course_scheme_needs_a_course_and_platform_scheme_must_not_have_one() -> None:
    with pytest.raises(LevelSchemeInvalidError):
        scheme(Curve.quadratic(50), scope="course", course_id=None).validate()
    with pytest.raises(LevelSchemeInvalidError):
        scheme(Curve.quadratic(50), scope="platform", course_id=uuid4()).validate()


def test_names_and_titles_need_all_three_locales() -> None:
    s = scheme(Curve.quadratic(50))
    s.name = {"en": "x"}
    with pytest.raises(LevelSchemeInvalidError):
        s.validate()


def test_a_harder_scheme_never_demotes_a_learner() -> None:
    """Levels are derived, but the shown level never drops below highest_level."""
    harder = scheme(Curve.quadratic(500))
    shown, highest, up = apply_xp(highest_level=4, xp=600, scheme=harder)
    assert shown == 4 and highest == 4 and up is False


def test_apply_xp_reports_level_up_and_raises_highest() -> None:
    shown, highest, up = apply_xp(1, 100, DEFAULT_SCHEME)
    assert (shown, highest, up) == (2, 2, True)


def test_apply_xp_same_level_is_not_a_level_up() -> None:
    assert apply_xp(2, 150, DEFAULT_SCHEME) == (2, 2, False)


def test_distribution_counts_learners_per_level() -> None:
    assert distribution([0, 50, 100, 350, 350], DEFAULT_SCHEME) == {1: 2, 2: 1, 3: 2}
