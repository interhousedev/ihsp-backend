"""LMS-18, WEB-23: choosing the next flash card within the daily limits."""

from datetime import UTC, datetime, timedelta

from app.modules.lms.domain.learning.cards import (
    NEW_PER_DAY,
    REVIEWS_PER_DAY,
    DailyUsage,
    end_of_local_day,
    format_interval,
    intervals_for,
    select_next,
    state_from_json,
    state_to_json,
)
from app.shared import srs
from app.shared.srs import CardState, Rating, SrsState

import pytest

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def stored(state: CardState, due: timedelta | None, **fields: float) -> dict:
    """A stored card state due `due` from NOW."""
    return state_to_json(
        SrsState(
            state=state,
            due_at=None if due is None else NOW + due,
            interval_days=float(fields.get("interval_days", 1)),
        )
    )


def test_new_cards_come_in_their_block_order() -> None:
    """WEB-23: with nothing else due, the first new card."""
    card, counts = select_next(["c1", "c2", "c3"], {}, NOW, DailyUsage())

    assert card == "c1"
    assert (counts.learning, counts.review, counts.new) == (0, 0, 3)


def test_the_session_order_is_learning_then_review_then_new() -> None:
    """WEB-23: due learning cards first, then reviews, then new cards."""
    states = {
        "review": stored(CardState.REVIEW, timedelta(hours=-1)),
        "learning": stored(CardState.LEARNING, timedelta(minutes=-1)),
    }
    cards = ["new", "review", "learning"]

    first, _ = select_next(cards, states, NOW, DailyUsage())
    second, _ = select_next(cards, {"review": states["review"]}, NOW, DailyUsage())
    third, _ = select_next(cards, {}, NOW, DailyUsage())

    assert (first, second, third) == ("learning", "review", "new")


def test_a_learning_card_that_is_not_due_yet_waits() -> None:
    """WEB-23: learning steps of 1 and 10 minutes."""
    states = {"c1": stored(CardState.LEARNING, timedelta(minutes=5))}

    card, counts = select_next(["c1"], states, NOW, DailyUsage())

    assert card is None
    assert counts.learning == 0


def test_a_review_card_due_later_today_is_offered_but_not_tomorrow() -> None:
    """WEB-23: reviews due before the end of the local day."""
    later_today = end_of_local_day(NOW) - timedelta(minutes=1)
    states = {
        "today": state_to_json(
            SrsState(state=CardState.REVIEW, due_at=later_today, interval_days=2)
        ),
        "tomorrow": state_to_json(
            SrsState(
                state=CardState.REVIEW,
                due_at=end_of_local_day(NOW) + timedelta(minutes=1),
                interval_days=2,
            )
        ),
    }

    card, counts = select_next(["tomorrow", "today"], states, NOW, DailyUsage())

    assert card == "today"
    assert counts.review == 1


def test_the_local_day_ends_at_tashkent_midnight() -> None:
    """GEN: Tashkent is UTC+5, so 09:00 UTC is 14:00 and the day ends at 19:00 UTC."""
    assert end_of_local_day(NOW) == datetime(2026, 10, 6, 19, 0, tzinfo=UTC)


def test_the_daily_new_card_limit_stops_new_cards() -> None:
    """WEB-23: 20 new cards a day."""
    cards = [f"c{i}" for i in range(30)]

    before, counts_before = select_next(cards, {}, NOW, DailyUsage(new=NEW_PER_DAY - 1))
    after, counts_after = select_next(cards, {}, NOW, DailyUsage(new=NEW_PER_DAY))

    assert before == "c0"
    assert counts_before.new == 1
    assert after is None
    assert counts_after.new == 0


def test_the_daily_review_limit_stops_reviews_but_not_learning() -> None:
    """WEB-23: 200 reviews a day; cards in learning are not counted."""
    states = {
        "r": stored(CardState.REVIEW, timedelta(hours=-1)),
        "l": stored(CardState.LEARNING, timedelta(minutes=-1)),
    }
    usage = DailyUsage(review=REVIEWS_PER_DAY)

    first, counts = select_next(["r", "l"], states, NOW, usage)
    second, _ = select_next(["r"], {"r": states["r"]}, NOW, usage)

    assert first == "l"
    assert counts.review == 0
    assert second is None


def test_a_card_state_survives_the_stored_json_form() -> None:
    """LMS-18: the state per card is stored as JSON in StepState.cards."""
    state = srs.review(SrsState(), Rating.EASY, NOW)

    assert state_from_json(state_to_json(state)) == state
    assert state_from_json(None) == SrsState()


@pytest.mark.parametrize(
    ("delta", "label"),
    [
        (timedelta(seconds=20), "1m"),
        (timedelta(minutes=10), "10m"),
        (timedelta(hours=3), "3h"),
        (timedelta(days=1), "1d"),
        (timedelta(days=4), "4d"),
        (timedelta(days=65), "2mo"),
        (timedelta(days=800), "2y"),
    ],
)
def test_button_labels_say_when_the_card_comes_back(
    delta: timedelta, label: str
) -> None:
    """WEB-23: each button shows the next interval."""
    assert format_interval(delta) == label


def test_a_new_card_shows_the_four_buttons() -> None:
    """WEB-23: again 1m, hard 1m, medium 10m, easy 4d for a new card."""
    assert intervals_for(SrsState(), NOW) == {
        "again": "1m",
        "hard": "1m",
        "medium": "10m",
        "easy": "4d",
    }
