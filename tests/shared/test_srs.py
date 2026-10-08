"""Anki-like scheduling (WEB-23)."""

from datetime import UTC, datetime, timedelta

from app.shared.srs import (
    MIN_EASE,
    CardState,
    Rating,
    SrsState,
    preview,
    review,
)

import pytest
from hypothesis import given
from hypothesis import strategies as st

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)

NEW = SrsState()
LEARNING_STEP_1 = SrsState(
    state=CardState.LEARNING, step=1, due_at=NOW + timedelta(minutes=10)
)
REVIEW_10D = SrsState(state=CardState.REVIEW, interval_days=10.0, ease=2.5, reps=3)
REVIEW_LOW_EASE = SrsState(state=CardState.REVIEW, interval_days=10.0, ease=1.35)
RELEARNING_5D = SrsState(
    state=CardState.RELEARNING,
    interval_days=5.0,
    ease=2.3,
    lapses=1,
    due_at=NOW + timedelta(minutes=10),
)


@pytest.mark.parametrize(
    ("start", "rating", "state", "step", "due", "interval", "ease"),
    [
        (NEW, Rating.AGAIN, CardState.LEARNING, 0, timedelta(minutes=1), 0.0, 2.5),
        (NEW, Rating.HARD, CardState.LEARNING, 0, timedelta(minutes=1), 0.0, 2.5),
        (NEW, Rating.MEDIUM, CardState.LEARNING, 1, timedelta(minutes=10), 0.0, 2.5),
        (
            LEARNING_STEP_1,
            Rating.MEDIUM,
            CardState.REVIEW,
            0,
            timedelta(days=1),
            1.0,
            2.5,
        ),
        (NEW, Rating.EASY, CardState.REVIEW, 0, timedelta(days=4), 4.0, 2.5),
        (
            REVIEW_10D,
            Rating.HARD,
            CardState.REVIEW,
            0,
            timedelta(days=12),
            12.0,
            2.35,
        ),
        (
            REVIEW_10D,
            Rating.MEDIUM,
            CardState.REVIEW,
            0,
            timedelta(days=25),
            25.0,
            2.5,
        ),
        (
            REVIEW_10D,
            Rating.EASY,
            CardState.REVIEW,
            0,
            timedelta(days=32.5),
            32.5,
            2.65,
        ),
        (
            REVIEW_10D,
            Rating.AGAIN,
            CardState.RELEARNING,
            0,
            timedelta(minutes=10),
            5.0,
            2.3,
        ),
        (
            REVIEW_LOW_EASE,
            Rating.AGAIN,
            CardState.RELEARNING,
            0,
            timedelta(minutes=10),
            5.0,
            MIN_EASE,
        ),
        (
            RELEARNING_5D,
            Rating.MEDIUM,
            CardState.REVIEW,
            0,
            timedelta(days=5),
            5.0,
            2.3,
        ),
    ],
)
def test_review_moves_the_card_as_in_the_table(
    start: SrsState,
    rating: Rating,
    state: CardState,
    step: int,
    due: timedelta,
    interval: float,
    ease: float,
) -> None:
    """WEB-23: every answer button schedules the card as the Anki-like table says."""
    result = review(start, rating, NOW)

    assert result.state == state
    assert result.step == step
    assert result.due_at == NOW + due
    assert result.interval_days == pytest.approx(interval)
    assert result.ease == pytest.approx(ease)


def test_again_on_a_review_card_counts_a_lapse() -> None:
    """WEB-23: forgetting a mature card adds one lapse."""
    result = review(REVIEW_10D, Rating.AGAIN, NOW)

    assert result.lapses == REVIEW_10D.lapses + 1


def test_relearning_again_keeps_the_card_in_relearning() -> None:
    """WEB-23: failing a relearning card repeats the step."""
    result = review(RELEARNING_5D, Rating.AGAIN, NOW)

    assert result.state == CardState.RELEARNING
    assert result.due_at == NOW + timedelta(minutes=10)


def test_preview_shows_every_button() -> None:
    """WEB-23: the UI shows the next interval on all four buttons."""
    result = preview(NEW, NOW)

    assert set(result) == set(Rating)
    assert result[Rating.AGAIN] == timedelta(minutes=1)
    assert result[Rating.EASY] == timedelta(days=4)


@given(st.lists(st.sampled_from(list(Rating)), max_size=60))
def test_ease_never_drops_below_the_minimum_and_due_is_never_in_the_past(
    ratings: list[Rating],
) -> None:
    """WEB-23: any answer history keeps ease >= 1.3 and due_at >= now."""
    card = SrsState()
    now = NOW

    for rating in ratings:
        card = review(card, rating, now)

        assert card.ease >= MIN_EASE
        assert card.due_at is not None
        assert card.due_at >= now
        now = card.due_at
