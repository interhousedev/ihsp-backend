"""WEB-24: editing the text of one card."""

from app.modules.flashcards.domain.errors import CardNotFoundError, InvalidCardsError
from app.shared.ids import new_id
from app.shared.srs import CardState, Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def test_front_back_or_both_can_be_changed(h: FlashcardsHarness) -> None:
    """WEB-24: a side that is not given keeps its text."""
    created = await h.make_set(1)
    card_id = created.cards[0].id

    only_front = await h.services.update_card.execute(
        owner_id=h.student.user_id, card_id=card_id, front="new front", back=None
    )
    only_back = await h.services.update_card.execute(
        owner_id=h.student.user_id, card_id=card_id, front=None, back="new back"
    )
    both = await h.services.update_card.execute(
        owner_id=h.student.user_id, card_id=card_id, front="F", back="B"
    )

    assert (only_front.front, only_front.back) == ("new front", "back 0")
    assert (only_back.front, only_back.back) == ("new front", "new back")
    assert (both.front, both.back) == ("F", "B")
    assert both.id == card_id and both.set_id == created.id and both.position == 0


async def test_the_progress_of_the_card_is_kept(h: FlashcardsHarness) -> None:
    """UF-WEB-23: edited cards keep their progress."""
    created = await h.make_set(1)
    card_id = created.cards[0].id
    await h.rate(card_id, Rating.EASY)

    edited = await h.services.update_card.execute(
        owner_id=h.student.user_id, card_id=card_id, front="changed", back=None
    )

    assert edited.state == "review" and edited.due_at is not None
    assert h.store.cards[card_id].state is CardState.REVIEW


@pytest.mark.parametrize(
    ("front", "back"), [("", None), (None, ""), ("f" * 2001, None)]
)
async def test_a_side_must_keep_1_to_2000_characters(
    h: FlashcardsHarness, front: str | None, back: str | None
) -> None:
    """Plan B10: front/back 1-2000 characters; the card is unchanged on failure."""
    created = await h.make_set(1)
    card_id = created.cards[0].id

    with pytest.raises(InvalidCardsError):
        await h.services.update_card.execute(
            owner_id=h.student.user_id, card_id=card_id, front=front, back=back
        )

    assert h.store.cards[card_id].front == "front 0"


async def test_a_card_of_another_students_set_is_not_found(
    h: FlashcardsHarness,
) -> None:
    """Ownership: 404 and the text stays."""
    created = await h.make_set(1)
    card_id = created.cards[0].id

    with pytest.raises(CardNotFoundError) as raised:
        await h.services.update_card.execute(
            owner_id=h.other_student.user_id, card_id=card_id, front="mine", back=None
        )

    assert raised.value.status == 404
    assert h.store.cards[card_id].front == "front 0"


async def test_an_unknown_card_is_not_found(h: FlashcardsHarness) -> None:
    """Ownership: unknown ids give 404."""
    with pytest.raises(CardNotFoundError):
        await h.services.update_card.execute(
            owner_id=h.student.user_id, card_id=new_id(), front="x", back=None
        )
