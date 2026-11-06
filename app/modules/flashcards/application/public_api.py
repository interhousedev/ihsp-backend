"""FlashcardsApi: what AI (B9), links (B7) and MCP (B15) may ask (contract § 3.6)."""

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any, Literal
from uuid import UUID

from app.modules.flashcards.application.add_cards import AddCards
from app.modules.flashcards.application.create_set import CreateSet
from app.modules.flashcards.application.delete_card import DeleteCard
from app.modules.flashcards.application.get_card_stats import GetCardStats
from app.modules.flashcards.application.list_sets import ListSets
from app.modules.flashcards.application.merge_sets import MergeSets
from app.modules.flashcards.application.restart_study import RestartStudy
from app.modules.flashcards.application.update_card import UpdateCard
from app.modules.flashcards.application.update_set import UpdateSet
from app.modules.flashcards.domain.errors import (
    FlashcardSetNotFoundError,
    InvalidCardsError,
)
from app.modules.flashcards.domain.flashcard import Flashcard, Hardness
from app.modules.flashcards.domain.flashcard_set import FlashcardSet, SetSource
from app.modules.flashcards.domain.limits import CARD_TEXT_MAX, MAX_CARDS_PER_SET
from app.modules.flashcards.ports.unit_of_work import UowFactory
from app.shared.contracts.flashcards import CardTuple


def _hardness(value: str | None) -> Hardness | None:
    if value is None:
        return None
    try:
        return Hardness(value)
    except ValueError as error:
        raise InvalidCardsError(
            params={
                "reason": "hardness",
                "max_cards": MAX_CARDS_PER_SET,
                "max_chars": CARD_TEXT_MAX,
            }
        ) from error


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
                "hardness": card.hardness.value,
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
        delete_card: DeleteCard,
        update_set: UpdateSet,
        merge_sets: MergeSets,
        restart_study: RestartStudy,
        get_card_stats: GetCardStats,
    ) -> None:
        """Store the collaborators."""
        self._delete_card = delete_card
        self._update_set = update_set
        self._merge_sets = merge_sets
        self._restart_study = restart_study
        self._get_card_stats = get_card_stats
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
        cards: Sequence[CardTuple],
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
        self, owner_id: UUID, set_id: UUID, cards: Sequence[CardTuple]
    ) -> dict[str, Any]:
        """Append a batch to the owner's set; return the set like `get_set`."""
        await self._add_cards.execute(owner_id=owner_id, set_id=set_id, cards=cards)
        return await self._read(set_id)

    async def update_card(
        self,
        owner_id: UUID,
        card_id: UUID,
        front: str | None,
        back: str | None,
        *,
        hardness: str | None = None,
    ) -> dict[str, Any]:
        """Edit one card; return `{id, set_id, position, front, back, hardness}`."""
        card = await self._update_card.execute(
            owner_id=owner_id,
            card_id=card_id,
            front=front,
            back=back,
            hardness=_hardness(hardness),
        )
        return {
            "id": card.id,
            "set_id": card.set_id,
            "position": card.position,
            "front": card.front,
            "back": card.back,
            "hardness": card.hardness,
        }

    async def delete_card(self, owner_id: UUID, card_id: UUID) -> None:
        """Delete one card of the owner's set."""
        await self._delete_card.execute(owner_id=owner_id, card_id=card_id)

    async def update_set_settings(
        self,
        owner_id: UUID,
        set_id: UUID,
        *,
        shuffle: bool | None = None,
        new_per_day: int | None = None,
        reviews_per_day: int | None = None,
    ) -> dict[str, Any]:
        """Change the settings that were given; return the set with its settings."""
        detail = await self._update_set.execute(
            owner_id=owner_id,
            set_id=set_id,
            shuffle=shuffle,
            new_per_day=new_per_day,
            reviews_per_day=reviews_per_day,
        )
        return {
            **await self._read(set_id),
            "shuffle": detail.shuffle,
            "new_per_day": detail.new_per_day,
            "reviews_per_day": detail.reviews_per_day,
        }

    async def merge_sets(
        self,
        owner_id: UUID,
        set_ids: Sequence[UUID],
        title: str,
        *,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a set from 2-20 sets; like `get_set` plus `duplicates_skipped`."""
        merged = await self._merge_sets.execute(
            owner_id=owner_id, set_ids=set_ids, title=title, description=description
        )
        return {
            **await self._read(merged.set.id),
            "duplicates_skipped": merged.duplicates_skipped,
        }

    async def restart_study(self, owner_id: UUID, set_id: UUID) -> dict[str, Any]:
        """Start today's practice round; return the study state as a dict."""
        return asdict(
            await self._restart_study.execute(owner_id=owner_id, set_id=set_id)
        )

    async def card_stats(self, owner_id: UUID, set_id: UUID) -> list[dict[str, Any]]:
        """Return attempts, correct, incorrect and last_studied_at per card."""
        rows = await self._get_card_stats.execute(owner_id=owner_id, set_id=set_id)
        return [asdict(row) for row in rows]

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
