"""Study order and daily limits (WEB-23): which card comes next."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.modules.flashcards.domain.flashcard import Flashcard
from app.shared.clock import TASHKENT, to_local
from app.shared.srs import CardState

_LEARNING = (CardState.LEARNING, CardState.RELEARNING)


@dataclass(frozen=True, slots=True)
class DailyUsage:
    """What the student already did in one set today."""

    new: int = 0
    review: int = 0


@dataclass(frozen=True, slots=True)
class StudyCounts:
    """Cards waiting in each queue (the offered card is included)."""

    learning: int
    review: int
    new: int


@dataclass(frozen=True, slots=True)
class StudyPlan:
    """The next card, or None when nothing is due right now."""

    card: Flashcard | None
    counts: StudyCounts


def study_day(now: datetime) -> date:
    """Return the study day (Tashkent calendar day) that `now` falls in."""
    return to_local(now).date()


def day_end(now: datetime) -> datetime:
    """Return the first moment after today's study day (exclusive end)."""
    tomorrow = study_day(now) + timedelta(days=1)
    return datetime.combine(tomorrow, time.min, tzinfo=TASHKENT)


def is_due_today(card: Flashcard, end_of_day: datetime) -> bool:
    """Return True for a card that has been seen and is due before the day ends."""
    return card.state is not CardState.NEW and (
        card.due_at is None or card.due_at < end_of_day
    )


def new_today(new_cards: int, new_per_day: int, introduced: int) -> int:
    """Return how many new cards may still be introduced today."""
    return min(new_cards, max(0, new_per_day - introduced))


def _in_states(cards: Sequence[Flashcard], *states: CardState) -> list[Flashcard]:
    return [card for card in cards if card.state in states]


def _due_key(now: datetime) -> Callable[[Flashcard], datetime]:
    return lambda card: card.due_at or now


def plan_study(
    cards: Sequence[Flashcard],
    *,
    new_per_day: int,
    reviews_per_day: int,
    usage: DailyUsage,
    now: datetime,
) -> StudyPlan:
    """Pick the next card: due learning, then reviews, then new cards.

    Learning and relearning cards are never limited. Reviews due before the day
    ends are limited by what is left of `reviews_per_day`, new cards by what is
    left of `new_per_day`.
    """
    end_of_day = day_end(now)
    due = _due_key(now)
    ordered = sorted(cards, key=lambda card: card.position)
    learning = sorted(_in_states(ordered, *_LEARNING), key=due)
    reviews = sorted(_in_states(ordered, CardState.REVIEW), key=due)

    learning_now = [card for card in learning if due(card) <= now]
    review_queue = [card for card in reviews if due(card) < end_of_day]
    review_queue = review_queue[: max(0, reviews_per_day - usage.review)]
    new_queue = _in_states(ordered, CardState.NEW)[: max(0, new_per_day - usage.new)]

    first = next((q[0] for q in (learning_now, review_queue, new_queue) if q), None)
    counts = StudyCounts(
        learning=sum(1 for card in learning if due(card) < end_of_day),
        review=len(review_queue),
        new=len(new_queue),
    )
    return StudyPlan(card=first, counts=counts)
