"""In-memory unit of work of the flashcards module (copies in and out, like a DB)."""

import copy
from collections.abc import Callable, Sequence
from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.flashcards.domain.flashcard import Flashcard
from app.modules.flashcards.domain.flashcard_set import FlashcardSet, SetCounts
from app.shared.srs import CardState


class FakeFlashcardsStore:
    """The "database": sets and cards shared by every unit of work."""

    def __init__(self) -> None:
        """Start empty."""
        self.sets: dict[UUID, FlashcardSet] = {}
        self.cards: dict[UUID, Flashcard] = {}
        self.commits = 0

    def cards_of(self, set_id: UUID) -> list[Flashcard]:
        """Return copies of a set's cards ordered by position (for assertions)."""
        rows = [c for c in self.cards.values() if c.set_id == set_id]
        return copy.deepcopy(sorted(rows, key=lambda c: c.position))


class FakeSetRepository:
    """Sets of a FakeFlashcardsStore."""

    def __init__(self, store: FakeFlashcardsStore) -> None:
        """Bind to the store."""
        self.store = store

    async def add(self, flashcard_set: FlashcardSet) -> None:
        """Insert a set."""
        self.store.sets[flashcard_set.id] = copy.deepcopy(flashcard_set)

    async def get(self, set_id: UUID) -> FlashcardSet | None:
        """Return a copy of the set."""
        found = self.store.sets.get(set_id)
        return copy.deepcopy(found) if found else None

    async def get_for_update(self, set_id: UUID) -> FlashcardSet | None:
        """Same as get (the fake has no row locks)."""
        return await self.get(set_id)

    async def save(self, flashcard_set: FlashcardSet) -> None:
        """Store the set's fields."""
        self.store.sets[flashcard_set.id] = copy.deepcopy(flashcard_set)

    async def delete(self, set_id: UUID) -> None:
        """Delete the set with its cards."""
        self.store.sets.pop(set_id, None)
        for card_id in [c.id for c in self.store.cards.values() if c.set_id == set_id]:
            del self.store.cards[card_id]

    async def list_for_owner(self, owner_id: UUID) -> list[FlashcardSet]:
        """Newest first."""
        rows = [s for s in self.store.sets.values() if s.owner_id == owner_id]
        rows.sort(key=lambda s: (s.created_at, s.id), reverse=True)
        return copy.deepcopy(rows)


class FakeCardRepository:
    """Cards of a FakeFlashcardsStore."""

    def __init__(self, store: FakeFlashcardsStore) -> None:
        """Bind to the store."""
        self.store = store

    async def add_many(self, cards: Sequence[Flashcard]) -> None:
        """Insert cards."""
        for card in cards:
            self.store.cards[card.id] = copy.deepcopy(card)

    async def get(self, card_id: UUID) -> Flashcard | None:
        """Return a copy of the card."""
        found = self.store.cards.get(card_id)
        return copy.deepcopy(found) if found else None

    async def get_for_update(self, card_id: UUID) -> Flashcard | None:
        """Same as get (the fake has no row locks)."""
        return await self.get(card_id)

    async def save(self, card: Flashcard) -> None:
        """Store the card's fields (only if it exists)."""
        if card.id in self.store.cards:
            self.store.cards[card.id] = copy.deepcopy(card)

    async def delete_many(self, card_ids: Sequence[UUID]) -> None:
        """Delete cards."""
        for card_id in card_ids:
            self.store.cards.pop(card_id, None)

    async def list_for_set(self, set_id: UUID) -> list[Flashcard]:
        """Cards ordered by position."""
        return self.store.cards_of(set_id)

    async def counts_for_sets(
        self, set_ids: Sequence[UUID], *, due_before: datetime
    ) -> dict[UUID, SetCounts]:
        """New cards and seen cards due before the bound, per set with cards."""
        result: dict[UUID, SetCounts] = {}
        for card in self.store.cards.values():
            if card.set_id not in set_ids:
                continue
            old = result.get(card.set_id, SetCounts())
            if card.state is CardState.NEW:
                result[card.set_id] = SetCounts(new=old.new + 1, due=old.due)
            elif card.due_at is not None and card.due_at < due_before:
                result[card.set_id] = SetCounts(new=old.new, due=old.due + 1)
            else:
                result[card.set_id] = old
        return result


class FakeFlashcardsUnitOfWork:
    """Unit of work over a store (writes apply at once; commit() only counts)."""

    def __init__(self, store: FakeFlashcardsStore) -> None:
        """Bind to the store."""
        self.store = store
        self.sets = FakeSetRepository(store)
        self.cards = FakeCardRepository(store)

    async def __aenter__(self) -> Self:
        """Open the unit of work."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Nothing to roll back."""

    async def commit(self) -> None:
        """Count the commit."""
        self.store.commits += 1


def fake_uow_factory(
    store: FakeFlashcardsStore,
) -> Callable[[], FakeFlashcardsUnitOfWork]:
    """Return a factory that makes a fresh unit of work per use."""
    return lambda: FakeFlashcardsUnitOfWork(store)
