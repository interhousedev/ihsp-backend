"""The flash card entity: text plus the spaced repetition state of its owner."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.modules.flashcards.domain.validation import check_card_text
from app.shared.ids import new_id
from app.shared.srs import CardState, Rating, SrsState
from app.shared.srs import review as srs_review


@dataclass(frozen=True, slots=True)
class CardDraft:
    """A card as the student typed it; `id` is set when an existing card is kept."""

    front: str
    back: str
    id: UUID | None = None


@dataclass(slots=True)
class Flashcard:
    """One card of a set (README → Flashcard)."""

    id: UUID
    set_id: UUID
    position: int
    front: str
    back: str
    srs: SrsState = field(default_factory=SrsState)
    last_reviewed_at: datetime | None = None

    @property
    def state(self) -> CardState:
        """Return the lifecycle state: new, learning, review or relearning."""
        return self.srs.state

    @property
    def due_at(self) -> datetime | None:
        """Return when the card comes back; None while it is new."""
        return self.srs.due_at

    def answer(self, rating: Rating, now: datetime) -> CardState:
        """Apply a rating (WEB-23); return the state the card had before it."""
        before = self.srs.state
        self.srs = srs_review(self.srs, rating, now)
        self.last_reviewed_at = now
        return before


def fresh_card(set_id: UUID, position: int, front: str, back: str) -> Flashcard:
    """Return a new card (state new) after checking its text."""
    check_card_text(front, back)
    return Flashcard(
        id=new_id(), set_id=set_id, position=position, front=front, back=back
    )
