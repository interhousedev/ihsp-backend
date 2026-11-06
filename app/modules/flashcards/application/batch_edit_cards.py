"""Use case: add, edit and delete cards of one set in one transaction (MCP A2)."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import SetDetailView
from app.modules.flashcards.domain.errors import (
    CardNotFoundError,
    FlashcardSetNotFoundError,
)
from app.modules.flashcards.domain.flashcard import (
    CardInput,
    Flashcard,
    as_draft,
    fresh_card,
)
from app.modules.flashcards.domain.validation import (
    check_card_count,
    check_card_text,
    check_unique_ids,
)
from app.modules.flashcards.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class CardChange:
    """New text of one card; a side that is None stays."""

    card_id: UUID
    front: str | None = None
    back: str | None = None


def _edited(card: Flashcard, change: CardChange) -> Flashcard:
    """Apply the change after checking it; the schedule of the card stays."""
    front = card.front if change.front is None else change.front
    back = card.back if change.back is None else change.back
    check_card_text(front, back)
    card.front, card.back = front, back
    return card


class BatchEditCards:
    """Everything is checked before the first write; any refusal changes nothing."""

    def __init__(self, *, uow_factory: UowFactory, views: SetViews) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(
        self,
        *,
        owner_id: UUID,
        set_id: UUID,
        add: Sequence[CardInput],
        update: Sequence[CardChange],
        delete_ids: Sequence[UUID],
    ) -> SetDetailView:
        """Apply the batch; an id outside the owner's set fails it with not found."""
        drafts = [as_draft(card) for card in add]
        for draft in drafts:
            check_card_text(draft.front, draft.back)
        check_unique_ids([*(change.card_id for change in update), *delete_ids])
        async with self.uow_factory() as uow:
            flashcard_set = await uow.sets.get_for_update(set_id)
            if flashcard_set is None or not flashcard_set.owned_by(owner_id):
                raise FlashcardSetNotFoundError()
            existing = {c.id: c for c in await uow.cards.list_for_set(set_id)}
            touched = [*(change.card_id for change in update), *delete_ids]
            if any(card_id not in existing for card_id in touched):
                raise CardNotFoundError()
            kept = len(existing) - len(delete_ids)
            check_card_count(kept + len(drafts))
            edited = [_edited(existing[c.card_id], c) for c in update]
            start = max((c.position for c in existing.values()), default=-1) + 1
            added = [
                fresh_card(set_id, start + offset, d.front, d.back, d.hardness)
                for offset, d in enumerate(drafts)
            ]
            await uow.cards.delete_many(list(delete_ids))
            for card in edited:
                await uow.cards.save(card)
            await uow.cards.add_many(added)
            flashcard_set.card_count = kept + len(added)
            await uow.sets.save(flashcard_set)
            await uow.commit()
        gone = set(delete_ids)
        cards = [c for c in existing.values() if c.id not in gone]
        ordered = sorted([*cards, *added], key=lambda card: card.position)
        return await self.views.detail(flashcard_set, ordered)
