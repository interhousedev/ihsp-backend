"""WEB-22, WEB-23: heatmap days, daily average, days learned and streaks."""

from datetime import date, timedelta

from app.modules.flashcards.domain.review_stats import (
    DayCount,
    compute_stats,
    current_streak,
    longest_streak,
)

TODAY = date(2026, 10, 8)


def days_ago(*offsets: int) -> set[date]:
    """Dates `offsets` days before TODAY."""
    return {TODAY - timedelta(days=offset) for offset in offsets}


def test_longest_streak_is_the_longest_run_of_consecutive_days() -> None:
    """Two runs (3 and 2 days) with a gap between them."""
    assert longest_streak(days_ago(0, 1, 2, 5, 6)) == 3


def test_longest_streak_of_no_days_is_zero() -> None:
    """Nothing studied, no streak."""
    assert longest_streak(set()) == 0


def test_current_streak_counts_back_from_today() -> None:
    """Studied today and the two days before."""
    assert current_streak(days_ago(0, 1, 2, 4), TODAY) == 3


def test_current_streak_survives_until_the_end_of_an_empty_today() -> None:
    """Nothing yet today, but yesterday and the day before count."""
    assert current_streak(days_ago(1, 2), TODAY) == 2


def test_current_streak_breaks_after_a_missed_day() -> None:
    """The last study day was two days ago."""
    assert current_streak(days_ago(2, 3), TODAY) == 0


def test_stats_of_a_student_who_never_studied_are_all_zero() -> None:
    """Nothing in the log."""
    stats = compute_stats({}, year=2026, today=TODAY, today_ms=0)

    assert stats.days == ()
    assert (stats.total_reviews, stats.days_studied) == (0, 0)
    assert (stats.daily_average, stats.days_learned_percent) == (0.0, 0.0)
    assert (stats.longest_streak, stats.current_streak) == (0, 0)
    assert stats.first_review_date is None
    assert (stats.today_count, stats.today_seconds) == (0, 0)


def test_heatmap_days_are_the_days_of_the_year_in_order() -> None:
    """Days of other years are not part of this year's heatmap."""
    counts = {
        date(2026, 3, 2): 5,
        date(2025, 12, 31): 9,
        date(2026, 1, 1): 2,
    }

    stats = compute_stats(counts, year=2026, today=TODAY, today_ms=0)

    assert stats.days == (
        DayCount(date(2026, 1, 1), 2),
        DayCount(date(2026, 3, 2), 5),
    )
    assert stats.total_reviews == 7


def test_daily_average_is_reviews_per_day_studied() -> None:
    """30 reviews over 4 studied days: 7.5 per day."""
    counts = {date(2026, 9, day): count for day, count in ((1, 10), (2, 5), (3, 5))}
    counts[date(2026, 9, 10)] = 10

    stats = compute_stats(counts, year=2026, today=TODAY, today_ms=0)

    assert (stats.total_reviews, stats.days_studied) == (30, 4)
    assert stats.daily_average == 7.5


def test_days_learned_is_the_share_of_days_since_the_first_review() -> None:
    """First review on Oct 1, today is Oct 8: 8 days, 2 of them studied."""
    counts = {date(2026, 10, 1): 3, date(2026, 10, 8): 4}

    stats = compute_stats(counts, year=2026, today=TODAY, today_ms=0)

    assert stats.days_learned_percent == 25.0


def test_days_learned_of_a_past_year_covers_the_whole_year() -> None:
    """In 2025 the student studied 73 of 365 days: 20 percent."""
    first = date(2025, 1, 1)
    counts = {first + timedelta(days=5 * i): 1 for i in range(73)}

    stats = compute_stats(counts, year=2025, today=TODAY, today_ms=0)

    assert stats.days_studied == 73
    assert stats.days_learned_percent == 20.0


def test_streaks_ignore_the_year_boundary() -> None:
    """A streak that began in December 2025 continues in January 2026."""
    counts = {date(2025, 12, 30): 1, date(2025, 12, 31): 1, date(2026, 1, 1): 1}

    stats = compute_stats(counts, year=2026, today=date(2026, 1, 1), today_ms=0)

    assert (stats.longest_streak, stats.current_streak) == (3, 3)
    assert stats.first_review_date == date(2025, 12, 30)


def test_today_numbers_come_from_today_only() -> None:
    """Studied N cards in X seconds today (milliseconds are rounded to seconds)."""
    counts = {TODAY: 12, TODAY - timedelta(days=1): 40}

    stats = compute_stats(counts, year=2026, today=TODAY, today_ms=45_400)

    assert (stats.today_count, stats.today_seconds) == (12, 45)
