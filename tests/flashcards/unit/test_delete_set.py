"""WEB-22: deleting a set removes its cards; only the owner can do it."""

from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.shared.ids import new_id
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def test_deleting_a_set_deletes_its_cards(h: FlashcardsHarness) -> None:
    """WEB-22: set and cards are gone, other sets stay."""
    doomed = await h.make_set(3)
    kept = await h.make_set(2, title="Kept")

    await h.services.delete_set.execute(owner_id=h.student.user_id, set_id=doomed.id)

    assert doomed.id not in h.store.sets and h.store.cards_of(doomed.id) == []
    assert len(h.store.cards_of(kept.id)) == 2


async def test_another_students_set_cannot_be_deleted(h: FlashcardsHarness) -> None:
    """Ownership: 404 and the set survives."""
    created = await h.make_set(1)

    with pytest.raises(FlashcardSetNotFoundError):
        await h.services.delete_set.execute(
            owner_id=h.other_student.user_id, set_id=created.id
        )

    assert created.id in h.store.sets


async def test_deleting_a_missing_set_is_not_found(h: FlashcardsHarness) -> None:
    """Ownership: unknown ids give 404."""
    with pytest.raises(FlashcardSetNotFoundError):
        await h.services.delete_set.execute(owner_id=h.student.user_id, set_id=new_id())
