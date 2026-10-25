"""FlashcardsApi: what AI (B9), links (B7) and MCP (B15) may ask (contract § 3.6)."""

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any, Literal
from uuid import UUID

from app.modules.flashcards.application.add_cards import AddCards
from app.modules.flashcards.application.create_set import CreateSet
from app.modules.flashcards.application.list_sets import ListSets
from app.modules.flashcards.application.update_card import UpdateCard
from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.modules.flashcards.domain.flashcard import Flashcard
from app.modules.flashcards.domain.flashcard_set import FlashcardSet, SetSource
from app.modules.flashcards.ports.unit_of_work import UowFactory


def _set_dict(
    flashcard_set: FlashcardSet, cards: Sequence[Flashcard]
) -> dict[str, Any]:
    """One set for other modules: no study state, so shares reveal no progress."""
    return {
        "id": flashcard_set.id,
        "owner_id": flashcard_set.owner_id,
        "title": flashcard_set.title,
        "description": flashcard_set.description,
        "source": flashcard_set.source.value,
        "card_count": flashcard_set.card_count,
        "cards": [
            {
                "id": card.id,
                "position": card.position,
                "front": card.front,
                "back": card.back,
            }
            for card in cards
        ],
    }


class FlashcardsApiImpl:
    """Implements `app.shared.contracts.flashcards.FlashcardsApi`."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        list_sets: ListSets,
        create_set: CreateSet,
        add_cards: AddCards,
        update_card: UpdateCard,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self._list_sets = list_sets
        self._create_set = create_set
        self._add_cards = add_cards
        self._update_card = update_card

    async def list_sets(self, owner_id: UUID) -> list[dict[str, Any]]:
        """Return the owner's sets with `card_count`, `due_today` and `new_today`."""
        items = await self._list_sets.execute(owner_id=owner_id)
        return [asdict(item) for item in items]

    async def get_set(
        self, set_id: UUID, owner_id: UUID | None
    ) -> dict[str, Any] | None:
        """Return a set with `cards[{id, position, front, back}]`.

        `owner_id=None` is the public read for shares; otherwise the set must belong
        to that user. Both return None for an unknown set.
        """
        async with self.uow_factory() as uow:
            flashcard_set = await uow.sets.get(set_id)
            if flashcard_set is None:
                return None
            if owner_id is not None and not flashcard_set.owned_by(owner_id):
                return None
            cards = await uow.cards.list_for_set(set_id)
        return _set_dict(flashcard_set, cards)

    async def create_set(
        self,
        owner_id: UUID,
        title: str,
        cards: Sequence[tuple[str, str]],
        *,
        source: Literal["manual", "ai", "mcp", "copied"],
        source_chat_id: UUID | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a set from (front, back) pairs; return it like `get_set`."""
        created = await self._create_set.execute(
            owner_id=owner_id,
            title=title,
            cards=cards,
            source=SetSource(source),
            source_chat_id=source_chat_id,
            description=description,
        )
        return await self._read(created.id)

    async def add_cards(
        self, owner_id: UUID, set_id: UUID, cards: Sequence[tuple[str, str]]
    ) -> dict[str, Any]:
        """Append cards to the owner's set; return the set like `get_set`."""
        await self._add_cards.execute(owner_id=owner_id, set_id=set_id, cards=cards)
        return await self._read(set_id)

    async def update_card(
        self, owner_id: UUID, card_id: UUID, front: str | None, back: str | None
    ) -> dict[str, Any]:
        """Edit one card; return `{id, set_id, position, front, back}`."""
        card = await self._update_card.execute(
            owner_id=owner_id, card_id=card_id, front=front, back=back
        )
        return {
            "id": card.id,
            "set_id": card.set_id,
            "position": card.position,
            "front": card.front,
            "back": card.back,
        }

    async def set_owner(self, set_id: UUID) -> UUID | None:
        """Return the owner of the set, None if it does not exist."""
        async with self.uow_factory() as uow:
            flashcard_set = await uow.sets.get(set_id)
        return flashcard_set.owner_id if flashcard_set else None

    async def _read(self, set_id: UUID) -> dict[str, Any]:
        found = await self.get_set(set_id, None)
        if found is None:
            raise FlashcardSetNotFoundError()
        return found
