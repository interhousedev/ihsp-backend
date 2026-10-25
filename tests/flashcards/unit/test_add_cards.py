"""WEB-24: appending cards (assistant and MCP clients)."""

from app.modules.flashcards.domain.errors import (
    FlashcardSetNotFoundError,
    InvalidCardsError,
)
from app.shared.srs import Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def test_cards_are_appended_after_the_last_one(h: FlashcardsHarness) -> None:
    """WEB-24: new cards get the next positions and the state `new`."""
    created = await h.make_set(2)

    updated = await h.services.add_cards.execute(
        owner_id=h.student.user_id,
        set_id=created.id,
        cards=[("added 1", "a1"), ("added 2", "a2")],
    )

    assert updated.card_count == 4 and h.store.sets[created.id].card_count == 4
    assert [(c.position, c.front, c.state) for c in updated.cards] == [
        (0, "front 0", "new"),
        (1, "front 1", "new"),
        (2, "added 1", "new"),
        (3, "added 2", "new"),
    ]
    assert [c.front for c in h.store.cards_of(created.id)][-2:] == [
        "added 1",
        "added 2",
    ]


async def test_existing_progress_is_untouched(h: FlashcardsHarness) -> None:
    """WEB-24: adding cards does not reset anything."""
    created = await h.make_set(1)
    await h.rate(created.cards[0].id, Rating.EASY)

    updated = await h.services.add_cards.execute(
        owner_id=h.student.user_id, set_id=created.id, cards=[("more", "more")]
    )

    assert [c.state for c in updated.cards] == ["review", "new"]


async def test_a_set_cannot_grow_past_500_cards(h: FlashcardsHarness) -> None:
    """Plan B10: cards <= 500 in total."""
    created = await h.make_set(499)

    with pytest.raises(InvalidCardsError):
        await h.services.add_cards.execute(
            owner_id=h.student.user_id,
            set_id=created.id,
            cards=[("a", "b"), ("c", "d")],
        )
    one_more = await h.services.add_cards.execute(
        owner_id=h.student.user_id, set_id=created.id, cards=[("a", "b")]
    )

    assert one_more.card_count == 500
    assert len(h.store.cards_of(created.id)) == 500


async def test_a_bad_card_adds_nothing(h: FlashcardsHarness) -> None:
    """Plan B10: front/back 1-2000 characters."""
    created = await h.make_set(1)

    with pytest.raises(InvalidCardsError):
        await h.services.add_cards.execute(
            owner_id=h.student.user_id,
            set_id=created.id,
            cards=[("fine", "fine"), ("x" * 2001, "back")],
        )

    assert len(h.store.cards_of(created.id)) == 1
    assert h.store.sets[created.id].card_count == 1


async def test_cards_cannot_be_added_to_another_students_set(
    h: FlashcardsHarness,
) -> None:
    """Ownership: 404 and the set is unchanged."""
    created = await h.make_set(1)

    with pytest.raises(FlashcardSetNotFoundError):
        await h.services.add_cards.execute(
            owner_id=h.other_student.user_id, set_id=created.id, cards=[("a", "b")]
        )

    assert len(h.store.cards_of(created.id)) == 1
