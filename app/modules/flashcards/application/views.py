"""What the use cases return (the HTTP layer maps these to the API contract)."""

from dataclasses import dataclass
from datetime import datetime
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
    """A set in the list (FlashcardSetItem)."""

    id: UUID
    title: str
    description: str | None
    source: str
    card_count: int
    due_today: int
    new_today: int


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
