"""WEB-22, WEB-23: the heatmap and numbers of the deck overview."""

from datetime import UTC, date, datetime

from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.shared.srs import Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def test_a_student_who_never_studied_has_an_empty_heatmap(
    h: FlashcardsHarness,
) -> None:
    """WEB-22: all zeros, the current year."""
    await h.make_set(2)

    result = await h.services.get_review_stats.execute(owner_id=h.student.user_id)

    assert result.year == 2026 and result.days == ()
    assert (result.today_count, result.today_seconds) == (0, 0)
    assert (result.current_streak, result.longest_streak) == (0, 0)
    assert result.first_review_date is None and result.set_id is None


async def test_each_rating_counts_towards_today(h: FlashcardsHarness) -> None:
    """WEB-23: three ratings today, 12.5 seconds in total."""
    created = await h.make_set(3)
    for card, ms in zip(created.cards, (2000, 4500, 6000), strict=True):
        await h.rate(card.id, Rating.EASY, duration_ms=ms)

    result = await h.services.get_review_stats.execute(owner_id=h.student.user_id)

    assert [(d.date, d.count) for d in result.days] == [(date(2026, 10, 6), 3)]
    assert (result.today_count, result.today_seconds) == (3, 13)
    assert (result.total_reviews, result.days_studied) == (3, 1)
    assert result.current_streak == 1


async def test_days_are_tashkent_days_not_utc_days(h: FlashcardsHarness) -> None:
    """WEB-23: 20:00 UTC is already the next day in Tashkent (UTC+5)."""
    created = await h.make_set(2)
    h.clock.set(datetime(2026, 10, 6, 18, 59, tzinfo=UTC))  # 23:59 Oct 6 in Tashkent
    await h.rate(created.cards[0].id, Rating.EASY)
    h.clock.set(datetime(2026, 10, 6, 19, 1, tzinfo=UTC))  # 00:01 Oct 7 in Tashkent
    await h.rate(created.cards[1].id, Rating.EASY)

    result = await h.services.get_review_stats.execute(owner_id=h.student.user_id)

    assert [(d.date, d.count) for d in result.days] == [
        (date(2026, 10, 6), 1),
        (date(2026, 10, 7), 1),
    ]
    assert (result.today_count, result.current_streak) == (1, 2)


async def test_streaks_follow_consecutive_days(h: FlashcardsHarness) -> None:
    """WEB-23: three days in a row, a gap, then today: longest 3, current 1."""
    created = await h.make_set(1)
    card = created.cards[0].id
    for _ in range(3):
        await h.rate(card, Rating.AGAIN)
        h.clock.advance(days=1)
    h.clock.advance(days=2)
    await h.rate(card, Rating.AGAIN)

    result = await h.services.get_review_stats.execute(owner_id=h.student.user_id)

    assert (result.longest_streak, result.current_streak) == (3, 1)
    assert result.first_review_date == date(2026, 10, 6)
    assert result.days_studied == 4


async def test_a_set_filter_counts_only_that_set(h: FlashcardsHarness) -> None:
    """WEB-22: the deck overview shows the deck, the deck list shows everything."""
    first = await h.make_set(2, title="First")
    second = await h.make_set(1, title="Second")
    await h.rate(first.cards[0].id, Rating.EASY)
    await h.rate(first.cards[1].id, Rating.EASY)
    await h.rate(second.cards[0].id, Rating.EASY)

    everything = await h.services.get_review_stats.execute(owner_id=h.student.user_id)
    only_second = await h.services.get_review_stats.execute(
        owner_id=h.student.user_id, set_id=second.id
    )

    assert everything.today_count == 3
    assert (only_second.today_count, only_second.set_id) == (1, second.id)


async def test_another_students_reviews_are_not_counted(h: FlashcardsHarness) -> None:
    """Privacy: the log is per user."""
    theirs = await h.make_set(1, owner=h.other_student)
    await h.rate(theirs.cards[0].id, Rating.EASY, owner=h.other_student)

    result = await h.services.get_review_stats.execute(owner_id=h.student.user_id)

    assert result.today_count == 0


async def test_the_year_can_be_chosen(h: FlashcardsHarness) -> None:
    """WEB-22: the heatmap has year navigation; streaks still see the history."""
    created = await h.make_set(1)
    await h.rate(created.cards[0].id, Rating.AGAIN)

    this_year = await h.services.get_review_stats.execute(owner_id=h.student.user_id)
    last_year = await h.services.get_review_stats.execute(
        owner_id=h.student.user_id, year=2025
    )

    assert (this_year.year, this_year.total_reviews) == (2026, 1)
    assert (last_year.year, last_year.total_reviews, last_year.days) == (2025, 0, ())
    assert last_year.current_streak == 1


async def test_another_students_set_is_not_found(h: FlashcardsHarness) -> None:
    """Ownership: asking for the stats of someone else's set gives 404."""
    theirs = await h.make_set(1, owner=h.other_student)

    with pytest.raises(FlashcardSetNotFoundError):
        await h.services.get_review_stats.execute(
            owner_id=h.student.user_id, set_id=theirs.id
        )
