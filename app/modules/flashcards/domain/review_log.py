"""One answered card in the review log (the source of the heatmap and streaks)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.shared.srs import CardState, Rating

# Anki's "maximum answer seconds": a card left open for an hour counts as a minute.
MAX_ANSWER_MS = 60_000


@dataclass(frozen=True, slots=True)
class ReviewLogEntry:
    """What happened when a card was rated (README → FlashcardReview)."""

    id: UUID
    user_id: UUID
    set_id: UUID
    card_id: UUID
    rating: Rating
    state_before: CardState
    interval_after_days: float
    reviewed_at: datetime
    duration_ms: int | None = None


def clamp_duration(duration_ms: int | None) -> int | None:
    """Return the time spent on a card, at most one minute; None when not measured."""
    if duration_ms is None:
        return None
    return max(0, min(duration_ms, MAX_ANSWER_MS))
