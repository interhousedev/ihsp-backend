"""Unit tests of XP levels, school-week streaks and FSRS scheduling."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.modules.lms.domain.engagement import fsrs
from app.modules.lms.domain.engagement.streak import (
    active_days_in_week,
    compute_streak,
)
from app.modules.lms.domain.engagement.xp import attempt_xp, level_of, xp_to_reach
from app.shared.clock import TASHKENT

# 2026-11-02 is a Monday.
MON = date(2026, 11, 2)


def days(*offsets: int) -> list[date]:
    """Dates relative to MON."""
    return [MON + timedelta(days=n) for n in offsets]


def test_level_curve() -> None:
    """Level L needs 50 * L * (L - 1) XP."""
    assert [xp_to_reach(n) for n in (1, 2, 3, 4)] == [0, 100, 300, 600]
    assert level_of(0).level == 1
    assert level_of(99).level == 1
    lvl = level_of(350)
    assert (lvl.level, lvl.xp_into_level, lvl.xp_for_next) == (3, 50, 300)


def test_attempt_xp_scales_with_score() -> None:
    """Flat 10 plus up to 20 for the score share."""
    assert attempt_xp(None, Decimal(10)) == 10
    assert attempt_xp(Decimal(5), Decimal(10)) == 20
    assert attempt_xp(Decimal(10), Decimal(10)) == 30


def test_weekend_rest_does_not_break_streak() -> None:
    """Mon-Fri active, idle weekend, Monday active: streak 6."""
    s = compute_streak(days(0, 1, 2, 3, 4, 7), MON + timedelta(days=7))
    assert s.current == 6
    assert s.today_done


def test_weekend_activity_is_bonus() -> None:
    """Saturday activity adds one and is marked bonus."""
    s = compute_streak(days(0, 1, 2, 3, 4, 5), MON + timedelta(days=6))
    assert s.current == 6
    assert s.week[5].state == "bonus"
    assert s.week[6].state == "pending"


def test_missed_weekday_without_freeze_resets() -> None:
    """Tuesday missed in the first week: the run restarts on Wednesday."""
    s = compute_streak(days(0, 2, 3), MON + timedelta(days=3))
    assert s.current == 2
    assert s.best == 2
    assert s.week[1].state == "missed"


def test_full_week_earns_a_freeze_that_covers_a_missed_day() -> None:
    """Full week 1 earns a freeze; Tuesday of week 2 is frozen, streak goes on."""
    today = MON + timedelta(days=9)  # Wednesday of week 2
    s = compute_streak(days(0, 1, 2, 3, 4, 7, 9), today)
    assert s.current == 7
    assert s.freezes == 0
    assert s.week[1].state == "freeze"


def test_freezes_are_capped_at_two() -> None:
    """Three full weeks hold only two freezes."""
    active = [d for w in range(3) for d in days(*(w * 7 + n for n in range(5)))]
    s = compute_streak(active, MON + timedelta(days=19))
    assert s.freezes == 2


def test_open_today_is_at_risk_not_broken() -> None:
    """An idle weekday today keeps the streak but flags the risk."""
    s = compute_streak(days(0, 1), MON + timedelta(days=2))
    assert s.current == 2
    assert s.at_risk
    assert not s.today_done
    weekend = compute_streak(days(0, 1, 2, 3, 4), MON + timedelta(days=5))
    assert not weekend.at_risk


def test_tashkent_date_boundary() -> None:
    """20:30 UTC on Monday is already Tuesday in Tashkent (UTC+5, no DST)."""
    late = datetime(2026, 11, 2, 20, 30, tzinfo=UTC)
    summer = datetime(2026, 7, 6, 20, 30, tzinfo=UTC)
    assert late.astimezone(TASHKENT).date() == date(2026, 11, 3)
    assert summer.astimezone(TASHKENT).utcoffset() == timedelta(hours=5)


def test_week_goal_counts_days_of_the_current_week() -> None:
    """Only days from Monday to today count."""
    assert active_days_in_week(days(-1, 0, 2, 2), MON + timedelta(days=3)) == 2


def test_fsrs_missed_item_is_due_now_and_intervals_grow() -> None:
    """Good answers push the due date further each time."""
    now = datetime(2026, 11, 2, 9, tzinfo=UTC)
    state = fsrs.new_item(now)
    assert state.due_at == now
    gaps = []
    for _ in range(4):
        state = fsrs.review(state, fsrs.GOOD, now)
        gaps.append(state.due_at - now)
        now = state.due_at
    assert gaps[0] >= timedelta(days=1)
    assert all(a < b for a, b in zip(gaps, gaps[1:], strict=False))
    assert state.reps == 4


def test_fsrs_again_relearns_in_ten_minutes_and_counts_lapse() -> None:
    """A wrong answer brings the item back soon and lowers stability."""
    now = datetime(2026, 11, 2, 9, tzinfo=UTC)
    good = fsrs.review(fsrs.new_item(now), fsrs.GOOD, now)
    later = good.due_at
    again = fsrs.review(good, fsrs.AGAIN, later)
    assert again.due_at == later + fsrs.RELEARN_DELAY
    assert again.stability <= good.stability
    assert again.lapses == 1
    assert again.difficulty > good.difficulty


def test_fsrs_interval_hits_target_retention() -> None:
    """At the scheduled interval the recall probability is about 90%."""
    stability = 10.0
    r = fsrs.retrievability(fsrs.interval_days(stability), stability)
    assert abs(r - fsrs.RETENTION) < 0.02
