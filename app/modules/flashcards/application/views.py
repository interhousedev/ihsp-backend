"""What the use cases return (the HTTP layer maps these to the API contract)."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CardView:
    """One card of a set with its study state."""

    id: UUID
    set_id: UUID
    position: int
    front: str
    back: str
    state: str
    due_at: datetime | None


@dataclass(frozen=True, slots=True)
class SetItemView:
    """A set in the list (FlashcardSetItem).

    `new_count`, `learning_count` and `due_count` are the three numbers of Anki's
    deck list, after the daily limits; `due_today` and `new_today` are the older
    names of the due total and `new_count`.
    """

    id: UUID
    title: str
    description: str | None
    source: str
    card_count: int
    due_today: int
    new_today: int
    new_count: int
    learning_count: int
    due_count: int


@dataclass(frozen=True, slots=True)
class SetDetailView(SetItemView):
    """A set with its cards and limits (FlashcardSetDetail)."""

    new_per_day: int
    reviews_per_day: int
    cards: tuple[CardView, ...]


@dataclass(frozen=True, slots=True)
class StudyCardView:
    """The card to show now (the back is sent with the front)."""

    id: UUID
    front: str
    back: str
    state: str


@dataclass(frozen=True, slots=True)
class IntervalsView:
    """When the card comes back after each button, e.g. "10m" or "4d"."""

    again: str
    hard: str
    medium: str
    easy: str


@dataclass(frozen=True, slots=True)
class CountsView:
    """Cards waiting in each queue."""

    learning: int
    review: int
    new: int


@dataclass(frozen=True, slots=True)
class StudyNextView:
    """The next card, the button labels and the queue sizes (StudyNext)."""

    set_id: UUID
    card: StudyCardView | None
    intervals: IntervalsView | None
    counts: CountsView
    done_for_today: bool


@dataclass(frozen=True, slots=True)
class DayCountView:
    """Reviews on one study day."""

    date: date
    count: int


@dataclass(frozen=True, slots=True)
class ReviewStatsView:
    """Heatmap and numbers of the deck overview (ReviewStats)."""

    year: int
    set_id: UUID | None
    days: tuple[DayCountView, ...]
    total_reviews: int
    days_studied: int
    daily_average: float
    days_learned_percent: float
    longest_streak: int
    current_streak: int
    first_review_date: date | None
    today_count: int
    today_seconds: int
