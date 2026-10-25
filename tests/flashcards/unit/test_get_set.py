"""WEB-22, WEB-24: opening a set; another student's set does not exist for me."""

from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.shared.ids import new_id
from app.shared.srs import Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def test_the_owner_sees_the_set_with_cards_and_progress(
    h: FlashcardsHarness,
) -> None:
    """WEB-24: cards in order, with state and due time."""
    created = await h.make_set(3)
    await h.rate(created.cards[1].id, Rating.EASY)

    opened = await h.services.get_set.execute(
        owner_id=h.student.user_id, set_id=created.id
    )

    assert opened.title == "Cells" and opened.card_count == 3
    assert [c.front for c in opened.cards] == ["front 0", "front 1", "front 2"]
    assert [c.state for c in opened.cards] == ["new", "review", "new"]
    assert opened.cards[0].due_at is None
    assert opened.cards[1].due_at is not None
    assert (opened.new_per_day, opened.reviews_per_day) == (20, 200)
    assert (opened.due_today, opened.new_today) == (0, 2)


async def test_another_students_set_is_not_found(h: FlashcardsHarness) -> None:
    """Ownership: a set of someone else answers like a missing set (404)."""
    created = await h.make_set(1)

    with pytest.raises(FlashcardSetNotFoundError) as raised:
        await h.services.get_set.execute(
            owner_id=h.other_student.user_id, set_id=created.id
        )

    assert raised.value.status == 404
    assert raised.value.code == "flashcards/set-not-found"


async def test_a_missing_set_is_not_found(h: FlashcardsHarness) -> None:
    """Ownership: unknown ids give the same answer."""
    with pytest.raises(FlashcardSetNotFoundError):
        await h.services.get_set.execute(owner_id=h.student.user_id, set_id=new_id())
