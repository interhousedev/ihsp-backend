"""Use case: save the full ordered list of cards of a set (WEB-24)."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import SetDetailView
from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.modules.flashcards.domain.flashcard import CardDraft, Flashcard, fresh_card
from app.modules.flashcards.domain.validation import (
    check_card_count,
    check_card_text,
    check_unique_ids,
)
from app.modules.flashcards.ports.unit_of_work import UowFactory


def _merge(
    set_id: UUID, existing: Mapping[UUID, Flashcard], drafts: Sequence[CardDraft]
) -> tuple[list[Flashcard], list[Flashcard]]:
    """Return (all cards in list order, the new ones); known ids keep their state."""
    ordered: list[Flashcard] = []
    added: list[Flashcard] = []
    for position, draft in enumerate(drafts):
        card = existing.get(draft.id) if draft.id else None
        if card is None:
            card = fresh_card(set_id, position, draft.front, draft.back)
            added.append(card)
        else:
            card.position, card.front, card.back = position, draft.front, draft.back
        ordered.append(card)
    return ordered, added


class ReplaceCards:
    """Makes the set's cards equal to the list: keep, add, reorder, delete."""

    def __init__(self, *, uow_factory: UowFactory, views: SetViews) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.views = views

    async def execute(
        self, *, owner_id: UUID, set_id: UUID, cards: Sequence[CardDraft]
    ) -> SetDetailView:
        """Cards with a known id keep their progress; missing ids are deleted."""
        check_card_count(len(cards))
        check_unique_ids([draft.id for draft in cards if draft.id])
        for draft in cards:
            check_card_text(draft.front, draft.back)
        async with self.uow_factory() as uow:
            flashcard_set = await uow.sets.get_for_update(set_id)
            if flashcard_set is None or not flashcard_set.owned_by(owner_id):
                raise FlashcardSetNotFoundError()
            existing = {c.id: c for c in await uow.cards.list_for_set(set_id)}
            ordered, added = _merge(set_id, existing, cards)
            kept = {card.id for card in ordered}
            await uow.cards.delete_many([cid for cid in existing if cid not in kept])
            for card in ordered:
                if card.id in existing:
                    await uow.cards.save(card)
            await uow.cards.add_many(added)
            flashcard_set.card_count = len(ordered)
            await uow.sets.save(flashcard_set)
            await uow.commit()
        return await self.views.detail(flashcard_set, ordered)
