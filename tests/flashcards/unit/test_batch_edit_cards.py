"""MCP A2: a batch of card changes applies whole or not at all, and keeps progress."""

from app.modules.flashcards.application.batch_edit_cards import CardChange
from app.modules.flashcards.domain.errors import CardNotFoundError, InvalidCardsError
from app.shared.srs import Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def test_batch_adds_updates_and_deletes(h: FlashcardsHarness) -> None:
    """MCP A2: all three kinds in one call; the count follows."""
    made = await h.make_set(3)
    first, second, third = made.cards

    result = await h.services.batch_edit_cards.execute(
        owner_id=h.student.user_id,
        set_id=made.id,
        add=[("new front", "new back")],
        update=[CardChange(card_id=first.id, front="edited")],
        delete_ids=[third.id],
    )

    assert result.card_count == 3
    assert [(c.front, c.back) for c in result.cards] == [
        ("edited", first.back),
        (second.front, second.back),
        ("new front", "new back"),
    ]
    assert result.cards[-1].position == third.position + 1


async def test_an_edit_keeps_the_progress_of_the_card(h: FlashcardsHarness) -> None:
    """MCP A2: an existing id keeps its schedule."""
    made = await h.make_set(1)
    card_id = made.cards[0].id
    await h.services.review_card.execute(
        owner_id=h.student.user_id, card_id=card_id, rating=Rating.EASY
    )
    before = h.store.cards[card_id].srs

    await h.services.batch_edit_cards.execute(
        owner_id=h.student.user_id,
        set_id=made.id,
        add=[],
        update=[CardChange(card_id=card_id, back="better")],
        delete_ids=[],
    )

    assert h.store.cards[card_id].srs == before
    assert h.store.cards[card_id].back == "better"


@pytest.mark.parametrize("kind", ["update", "delete"])
async def test_a_card_of_another_set_fails_the_whole_batch(
    h: FlashcardsHarness, kind: str
) -> None:
    """MCP A2: a foreign id gives not found and changes nothing."""
    mine = await h.make_set(2)
    theirs = await h.make_set(1, owner=h.other_student)
    foreign = theirs.cards[0].id
    before = {card_id: card.front for card_id, card in h.store.cards.items()}

    with pytest.raises(CardNotFoundError):
        await h.services.batch_edit_cards.execute(
            owner_id=h.student.user_id,
            set_id=mine.id,
            add=[("a", "b")],
            update=[CardChange(card_id=foreign, front="x")] if kind == "update" else [],
            delete_ids=[foreign] if kind == "delete" else [mine.cards[0].id],
        )

    assert {c: card.front for c, card in h.store.cards.items()} == before


async def test_someone_elses_set_is_not_found(h: FlashcardsHarness) -> None:
    """Rule 2: another student's set answers like a missing one."""
    theirs = await h.make_set(1, owner=h.other_student)

    with pytest.raises(Exception) as caught:
        await h.services.batch_edit_cards.execute(
            owner_id=h.student.user_id,
            set_id=theirs.id,
            add=[("a", "b")],
            update=[],
            delete_ids=[],
        )

    assert caught.value.status == 404  # type: ignore[attr-defined]
    assert len(h.store.cards) == 1


async def test_bad_text_and_the_card_limit_change_nothing(h: FlashcardsHarness) -> None:
    """MCP A2: limits are checked before the first write."""
    made = await h.make_set(499)
    delete_first = [made.cards[0].id]

    with pytest.raises(InvalidCardsError):
        await h.services.batch_edit_cards.execute(
            owner_id=h.student.user_id,
            set_id=made.id,
            add=[("a", "b")] * 3,
            update=[],
            delete_ids=delete_first,
        )
    with pytest.raises(InvalidCardsError):
        await h.services.batch_edit_cards.execute(
            owner_id=h.student.user_id,
            set_id=made.id,
            add=[],
            update=[CardChange(card_id=made.cards[1].id, front="")],
            delete_ids=delete_first,
        )

    assert made.cards[0].id in h.store.cards
    assert len(h.store.cards) == 499


async def test_one_card_cannot_be_edited_and_deleted_together(
    h: FlashcardsHarness,
) -> None:
    """MCP A2: an id appears once in a batch."""
    made = await h.make_set(1)
    card_id = made.cards[0].id

    with pytest.raises(InvalidCardsError):
        await h.services.batch_edit_cards.execute(
            owner_id=h.student.user_id,
            set_id=made.id,
            add=[],
            update=[CardChange(card_id=card_id, front="x")],
            delete_ids=[card_id],
        )

    assert h.store.cards[card_id].front == made.cards[0].front
