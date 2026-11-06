"""The flash card entity: text plus the spaced repetition state of its owner."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.modules.flashcards.domain.errors import InvalidCardsError
from app.modules.flashcards.domain.limits import CARD_TEXT_MAX, MAX_CARDS_PER_SET
from app.modules.flashcards.domain.validation import check_card_text
from app.shared.ids import new_id
from app.shared.srs import START_EASE, CardState, Rating, SrsState
from app.shared.srs import review as srs_review

_EASE_STEP = 0.3


class Hardness(StrEnum):
    """How hard the author expects a card to be."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


def initial_srs(hardness: Hardness) -> SrsState:
    """Return the schedule a never-answered card starts with.

    Medium is the scheduler's plain start, so older cards behave as before. Hard
    starts with a lower ease (its intervals grow slower); easy starts with a higher
    ease and skips the first learning step (Good graduates it at once).
    """
    if hardness is Hardness.HARD:
        return SrsState(ease=START_EASE - _EASE_STEP)
    if hardness is Hardness.EASY:
        return SrsState(ease=START_EASE + _EASE_STEP, step=1)
    return SrsState()


@dataclass(frozen=True, slots=True)
class CardDraft:
    """A card as the student typed it; `id` is set when an existing card is kept.

    `hardness` None means "keep it" for a known card and medium for a new one.
    """

    front: str
    back: str
    id: UUID | None = None
    hardness: Hardness | None = None


CardInput = tuple[str, str] | tuple[str, str, str] | CardDraft


def as_draft(card: CardInput) -> CardDraft:
    """Normalise (front, back), (front, back, hardness) or a draft; check hardness."""
    if isinstance(card, CardDraft):
        return card
    if len(card) == 2:
        return CardDraft(card[0], card[1])
    try:
        return CardDraft(card[0], card[1], hardness=Hardness(card[2]))
    except ValueError as error:
        raise InvalidCardsError(
            params={
                "reason": "hardness",
                "max_cards": MAX_CARDS_PER_SET,
                "max_chars": CARD_TEXT_MAX,
            }
        ) from error


@dataclass(slots=True)
class Flashcard:
    """One card of a set (spec → Flashcard)."""

    id: UUID
    set_id: UUID
    position: int
    front: str
    back: str
    srs: SrsState = field(default_factory=SrsState)
    last_reviewed_at: datetime | None = None
    hardness: Hardness = Hardness.MEDIUM

    def set_hardness(self, hardness: Hardness) -> None:
        """Change the base hardness; only a never-answered card is rescheduled.

        Once a card has answers its ease and intervals reflect real results, which
        are worth more than the label, so a studied card keeps its schedule.
        """
        self.hardness = hardness
        if self.srs.state is CardState.NEW and self.srs.reps == 0:
            self.srs = initial_srs(hardness)

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


def fresh_card(
    set_id: UUID,
    position: int,
    front: str,
    back: str,
    hardness: Hardness | None = None,
) -> Flashcard:
    """Return a new card (state new) after checking its text."""
    check_card_text(front, back)
    base = hardness or Hardness.MEDIUM
    return Flashcard(
        id=new_id(),
        set_id=set_id,
        position=position,
        front=front,
        back=back,
        srs=initial_srs(base),
        hardness=base,
    )
