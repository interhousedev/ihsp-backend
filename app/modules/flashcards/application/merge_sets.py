"""Use case: combine several of the owner's sets into a new one.

The sources stay as they are. The copies start with fresh progress (it belongs to
the source card) and keep their base hardness. A card is a duplicate only when both
its question and its answer match after ignoring case and repeated spaces; the first
copy wins. The same question with another answer is kept, because only the student
can tell which answer is right.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import SetDetailView
from app.modules.flashcards.domain.errors import (
    FlashcardSetNotFoundError,
    InvalidMergeError,
)
from app.modules.flashcards.domain.flashcard import Flashcard, fresh_card
from app.modules.flashcards.domain.flashcard_set import FlashcardSet, SetSource
from app.modules.flashcards.domain.limits import MERGE_SETS_MAX, MERGE_SETS_MIN
from app.modules.flashcards.domain.validation import (
    check_card_count,
    clean_description,
    clean_title,
)
from app.modules.flashcards.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class MergedSetView:
    """The new set and how many duplicate cards were left out."""

    set: SetDetailView
    duplicates_skipped: int


def _fingerprint(card: Flashcard) -> tuple[str, str]:
    return (
        " ".join(card.front.split()).casefold(),
        " ".join(card.back.split()).casefold(),
    )


def _unique(cards: Iterable[Flashcard]) -> list[Flashcard]:
    seen: set[tuple[str, str]] = set()
    kept: list[Flashcard] = []
    for card in cards:
        mark = _fingerprint(card)
        if mark not in seen:
            seen.add(mark)
            kept.append(card)
    return kept


class MergeSets:
    """Creates a set from the cards of 2 to 20 sets, in the order given."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, views: SetViews
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.views = views

    async def execute(
        self,
        *,
        owner_id: UUID,
        set_ids: Sequence[UUID],
        title: str,
        description: str | None = None,
    ) -> MergedSetView:
        """Copy the cards; any id that is not the owner's set is "not found"."""
        distinct = list(dict.fromkeys(set_ids))
        if not MERGE_SETS_MIN <= len(distinct) <= MERGE_SETS_MAX:
            raise InvalidMergeError(
                params={"min": MERGE_SETS_MIN, "max": MERGE_SETS_MAX}
            )
        merged = FlashcardSet(
            id=new_id(),
            owner_id=owner_id,
            title=clean_title(title),
            created_at=self.clock.now(),
            source=SetSource.COPIED,
            description=clean_description(description),
        )
        async with self.uow_factory() as uow:
            originals: list[Flashcard] = []
            for set_id in distinct:
                source = await uow.sets.get(set_id)
                if source is None or not source.owned_by(owner_id):
                    raise FlashcardSetNotFoundError()
                originals.extend(await uow.cards.list_for_set(set_id))
            unique = _unique(originals)
            check_card_count(len(unique))
            cards = [
                fresh_card(merged.id, position, c.front, c.back, c.hardness)
                for position, c in enumerate(unique)
            ]
            merged.card_count = len(cards)
            await uow.sets.add(merged)
            await uow.cards.add_many(cards)
            await uow.commit()
        return MergedSetView(
            set=await self.views.detail(merged, cards),
            duplicates_skipped=len(originals) - len(unique),
        )
