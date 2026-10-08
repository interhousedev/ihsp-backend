"""Studying the flash cards of a block with Anki-like scheduling (LMS-18).

Daily limits and the order of a session follow WEB-23: due learning cards, then
reviews due today within the daily review limit, then new cards within the daily
new-card limit.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Final

from app.shared import srs
from app.shared.clock import TASHKENT
from app.shared.srs import CardState, Rating, SrsState

NEW_PER_DAY: Final = 20
REVIEWS_PER_DAY: Final = 200

_MINUTE: Final = timedelta(minutes=1)
_HOUR: Final = timedelta(hours=1)
_DAY: Final = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class DailyUsage:
    """Cards a learner already introduced or reviewed today in one block."""

    new: int = 0
    review: int = 0


@dataclass(frozen=True, slots=True)
class CardCounts:
    """What a study session still offers today."""

    learning: int
    review: int
    new: int

    @property
    def total(self) -> int:
        """Return all cards offered today."""
        return self.learning + self.review + self.new


# - - - Stored state - - -


def state_to_json(state: SrsState) -> dict[str, Any]:
    """Return the stored form of a card state."""
    return {
        "state": state.state.value,
        "step": state.step,
        "due_at": state.due_at.isoformat() if state.due_at else None,
        "interval_days": state.interval_days,
        "ease": state.ease,
        "reps": state.reps,
        "lapses": state.lapses,
    }


def state_from_json(raw: Mapping[str, Any] | None) -> SrsState:
    """Read a stored card state; a missing one is a new card."""
    if not raw:
        return SrsState()
    due = raw.get("due_at")
    return SrsState(
        state=CardState(raw.get("state", CardState.NEW.value)),
        step=int(raw.get("step", 0)),
        due_at=datetime.fromisoformat(due) if due else None,
        interval_days=float(raw.get("interval_days", 0.0)),
        ease=float(raw.get("ease", srs.START_EASE)),
        reps=int(raw.get("reps", 0)),
        lapses=int(raw.get("lapses", 0)),
    )


# - - - Selecting the next card - - -


def end_of_local_day(now: datetime) -> datetime:
    """Return the next Tashkent midnight as a UTC moment."""
    local = now.astimezone(TASHKENT)
    midnight = datetime.combine(local.date() + _DAY, time.min, tzinfo=TASHKENT)
    return midnight.astimezone(UTC)


def select_next(
    card_ids: Sequence[str],
    states: Mapping[str, Mapping[str, Any]],
    now: datetime,
    usage: DailyUsage,
) -> tuple[str | None, CardCounts]:
    """Return the id of the next card to study and the counts left today.

    ``card_ids`` is the block's cards in their order; cards without a stored
    state are new. Learning cards are served only when due; reviews due before
    the end of the local day; new cards while the daily limits allow.
    """
    learning: list[tuple[datetime, str]] = []
    reviews: list[tuple[datetime, str]] = []
    new: list[str] = []
    day_end = end_of_local_day(now)
    for card_id in card_ids:
        state = state_from_json(states.get(card_id))
        due = state.due_at or now
        if state.state == CardState.NEW:
            new.append(card_id)
        elif state.state == CardState.REVIEW:
            if due < day_end:
                reviews.append((due, card_id))
        elif due <= now:
            learning.append((due, card_id))
    learning.sort()
    reviews.sort()
    reviews_left = max(0, REVIEWS_PER_DAY - usage.review)
    new_left = max(0, NEW_PER_DAY - usage.new)
    counts = CardCounts(
        learning=len(learning),
        review=min(len(reviews), reviews_left),
        new=min(len(new), new_left),
    )
    return _first(learning, reviews[:reviews_left], new[:new_left]), counts


def _first(
    learning: list[tuple[datetime, str]],
    reviews: list[tuple[datetime, str]],
    new: list[str],
) -> str | None:
    """Return the first card in session order."""
    if learning:
        return learning[0][1]
    if reviews:
        return reviews[0][1]
    return new[0] if new else None


def counts_as_new(state: SrsState) -> bool:
    """Return True if reviewing a card in this state introduces a new card."""
    return state.state == CardState.NEW


def counts_as_review(state: SrsState) -> bool:
    """Return True if reviewing a card in this state uses the daily review limit."""
    return state.state == CardState.REVIEW


# - - - Buttons - - -


def intervals_for(state: SrsState, now: datetime) -> dict[str, str]:
    """Return the label of each button: when the card would come back."""
    preview = srs.preview(state, now)
    return {rating.value: format_interval(preview[rating]) for rating in Rating}


def format_interval(delta: timedelta) -> str:
    """Format a delay as ``1m``, ``10m``, ``3h``, ``4d``, ``2mo`` or ``1y``."""
    if delta < _HOUR:
        return f"{max(1, round(delta / _MINUTE))}m"
    if delta < _DAY:
        return f"{round(delta / _HOUR)}h"
    days = delta / _DAY
    if days < 30:
        return f"{round(days)}d"
    if days < 365:
        return f"{round(days / 30)}mo"
    return f"{round(days / 365)}y"
