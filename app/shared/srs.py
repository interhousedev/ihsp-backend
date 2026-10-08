"""Anki-like spaced repetition scheduler."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

LEARNING_STEPS = (timedelta(minutes=1), timedelta(minutes=10))
RELEARNING_STEP = timedelta(minutes=10)
GRADUATING_INTERVAL_DAYS = 1.0
EASY_INTERVAL_DAYS = 4.0
START_EASE = 2.5
MIN_EASE = 1.3


class CardState(StrEnum):
    """Lifecycle state of a card."""

    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


class Rating(StrEnum):
    """Answer buttons."""

    AGAIN = "again"
    HARD = "hard"
    MEDIUM = "medium"
    EASY = "easy"


@dataclass(frozen=True, slots=True)
class SrsState:
    """Scheduling state of one card for one learner."""

    state: CardState = CardState.NEW
    step: int = 0
    due_at: datetime | None = None
    interval_days: float = 0.0
    ease: float = START_EASE
    reps: int = 0
    lapses: int = 0


def review(card: SrsState, rating: Rating, now: datetime) -> SrsState:
    """Return the new state after answering a card."""
    if card.state in (CardState.NEW, CardState.LEARNING):
        return _learning(card, rating, now)
    if card.state == CardState.RELEARNING:
        return _relearning(card, rating, now)
    return _review(card, rating, now)


def _graduate(card: SrsState, days: float, now: datetime) -> SrsState:
    return replace(
        card,
        state=CardState.REVIEW,
        step=0,
        interval_days=days,
        due_at=now + timedelta(days=days),
        reps=card.reps + 1,
    )


def _learning(card: SrsState, rating: Rating, now: datetime) -> SrsState:
    if rating == Rating.EASY:
        return _graduate(card, EASY_INTERVAL_DAYS, now)
    if rating == Rating.AGAIN:
        step = 0
    elif rating == Rating.HARD:
        step = card.step
    else:
        step = card.step + 1
    if step >= len(LEARNING_STEPS):
        return _graduate(card, GRADUATING_INTERVAL_DAYS, now)
    return replace(
        card,
        state=CardState.LEARNING,
        step=step,
        due_at=now + LEARNING_STEPS[step],
    )


def _relearning(card: SrsState, rating: Rating, now: datetime) -> SrsState:
    if rating == Rating.AGAIN:
        return replace(card, due_at=now + RELEARNING_STEP)
    days = max(1.0, card.interval_days)
    return replace(
        card,
        state=CardState.REVIEW,
        interval_days=days,
        due_at=now + timedelta(days=days),
        reps=card.reps + 1,
    )


def _review(card: SrsState, rating: Rating, now: datetime) -> SrsState:
    if rating == Rating.AGAIN:
        return replace(
            card,
            state=CardState.RELEARNING,
            step=0,
            ease=max(MIN_EASE, card.ease - 0.20),
            lapses=card.lapses + 1,
            interval_days=max(1.0, card.interval_days * 0.5),
            due_at=now + RELEARNING_STEP,
        )
    if rating == Rating.HARD:
        ease, days = max(MIN_EASE, card.ease - 0.15), card.interval_days * 1.2
    elif rating == Rating.MEDIUM:
        ease, days = card.ease, card.interval_days * card.ease
    else:
        ease = card.ease + 0.15
        days = card.interval_days * card.ease * 1.3
    days = max(1.0, days)
    return replace(
        card,
        ease=ease,
        interval_days=days,
        due_at=now + timedelta(days=days),
        reps=card.reps + 1,
    )


def preview(card: SrsState, now: datetime) -> dict[Rating, timedelta]:
    """Return how far in the future each button would schedule the card."""
    result: dict[Rating, timedelta] = {}
    for rating in Rating:
        nxt = review(card, rating, now)
        result[rating] = (nxt.due_at or now) - now
    return result
