"""FSRS-4.5 scheduling of missed test questions (in-house, no dependency).

Ratings: 1 again, 2 hard, 3 good, 4 easy. A correct review answer is Good, a
wrong one Again. Intervals target a 90% recall probability; a lapse comes back
after `RELEARN_DELAY`.
"""

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final

W: Final = (
    0.4072,
    1.1829,
    3.1262,
    15.4722,
    7.2102,
    0.5316,
    1.0651,
    0.0234,
    1.616,
    0.1544,
    1.0824,
    1.9813,
    0.0953,
    0.2975,
    2.2042,
    0.2407,
    2.9466,
)
DECAY: Final = -0.5
FACTOR: Final = 19 / 81
RETENTION: Final = 0.9
MAX_INTERVAL_DAYS: Final = 365
RELEARN_DELAY: Final = timedelta(minutes=10)

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4


@dataclass(frozen=True, slots=True)
class FsrsState:
    """Memory state of one item; `stability` in days, `difficulty` 1..10."""

    stability: float
    difficulty: float
    due_at: datetime
    last_review_at: datetime | None = None
    reps: int = 0
    lapses: int = 0


def _clamp_difficulty(d: float) -> float:
    return min(max(d, 1.0), 10.0)


def _initial_stability(rating: int) -> float:
    return max(W[rating - 1], 0.1)


def _initial_difficulty(rating: int) -> float:
    return _clamp_difficulty(W[4] - W[5] * (rating - 3))


def retrievability(elapsed_days: float, stability: float) -> float:
    """Return the recall probability after `elapsed_days`."""
    return float((1 + FACTOR * elapsed_days / stability) ** DECAY)


def interval_days(stability: float) -> int:
    """Return the whole-day interval that hits the target retention."""
    days = stability / FACTOR * (RETENTION ** (1 / DECAY) - 1)
    return int(min(max(round(days), 1), MAX_INTERVAL_DAYS))


def new_item(now: datetime) -> FsrsState:
    """Return the state of a question just missed in a test (due now)."""
    return FsrsState(
        stability=_initial_stability(AGAIN),
        difficulty=_initial_difficulty(AGAIN),
        due_at=now,
    )


def _next_difficulty(d: float, rating: int) -> float:
    nd = d - W[6] * (rating - 3)
    # mean reversion towards the initial difficulty of Easy
    return _clamp_difficulty(W[7] * _initial_difficulty(EASY) + (1 - W[7]) * nd)


def _recall_stability(d: float, s: float, r: float, rating: int) -> float:
    hard = W[15] if rating == HARD else 1.0
    easy = W[16] if rating == EASY else 1.0
    return float(s) * float(
        1
        + math.exp(W[8])
        * (11 - d)
        * s ** (-W[9])
        * (math.exp((1 - r) * W[10]) - 1)
        * hard
        * easy
    )


def _forget_stability(d: float, s: float, r: float) -> float:
    return min(
        float(
            W[11] * d ** (-W[12]) * ((s + 1) ** W[13] - 1) * math.exp((1 - r) * W[14])
        ),
        s,
    )


def review(state: FsrsState, rating: int, now: datetime) -> FsrsState:
    """Apply one rating and return the next state with its due time."""
    if rating not in (AGAIN, HARD, GOOD, EASY):
        raise ValueError(f"rating must be 1..4, got {rating}")
    if state.last_review_at is None:
        stability = _initial_stability(rating)
        difficulty = _initial_difficulty(rating)
    else:
        elapsed = max((now - state.last_review_at).total_seconds() / 86400, 0.0)
        r = retrievability(elapsed, state.stability)
        difficulty = _next_difficulty(state.difficulty, rating)
        stability = (
            _forget_stability(state.difficulty, state.stability, r)
            if rating == AGAIN
            else _recall_stability(state.difficulty, state.stability, r, rating)
        )
    stability = max(stability, 0.1)
    due = (
        now + RELEARN_DELAY
        if rating == AGAIN
        else now + timedelta(days=interval_days(stability))
    )
    return replace(
        state,
        stability=stability,
        difficulty=difficulty,
        due_at=due,
        last_review_at=now,
        reps=state.reps + 1,
        lapses=state.lapses + (1 if rating == AGAIN and state.reps > 0 else 0),
    )
