"""WEB-24: saving the full ordered list of cards keeps progress of kept cards."""

from app.modules.flashcards.domain.errors import (
    FlashcardSetNotFoundError,
    InvalidCardsError,
)
from app.modules.flashcards.domain.flashcard import CardDraft
from app.shared.ids import new_id
from app.shared.srs import CardState, Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def test_kept_cards_keep_their_progress_and_new_cards_start_new(
    h: FlashcardsHarness,
) -> None:
    """UF-WEB-23: edited cards keep their progress; added cards are `new`."""
    created = await h.make_set(2)
    studied, other = created.cards
    await h.rate(studied.id, Rating.EASY)
    due_before = h.store.cards[studied.id].due_at

    saved = await h.replace(
        created.id,
        [
            CardDraft("edited front", "edited back", studied.id),
            CardDraft("added front", "added back"),
            CardDraft(other.front, other.back, other.id),
        ],
    )

    assert [c.front for c in saved.cards] == ["edited front", "added front", "front 1"]
    assert saved.cards[0].id == studied.id and saved.cards[2].id == other.id
    assert saved.cards[1].id not in {studied.id, other.id}
    assert [c.state for c in saved.cards] == ["review", "new", "new"]
    kept = h.store.cards[studied.id]
    assert kept.state is CardState.REVIEW and kept.due_at == due_before
    assert kept.srs.reps == 1


async def test_positions_follow_the_list_order(h: FlashcardsHarness) -> None:
    """WEB-24: reordering is saving the list in a new order."""
    created = await h.make_set(3)
    a, b, c = created.cards

    saved = await h.replace(
        created.id,
        [CardDraft(c.front, c.back, c.id), CardDraft(a.front, a.back, a.id)]
        + [CardDraft(b.front, b.back, b.id)],
    )

    assert [(x.id, x.position) for x in saved.cards] == [
        (c.id, 0),
        (a.id, 1),
        (b.id, 2),
    ]
    assert [x.id for x in h.store.cards_of(created.id)] == [c.id, a.id, b.id]


async def test_missing_ids_are_deleted_and_the_count_is_updated(
    h: FlashcardsHarness,
) -> None:
    """WEB-24: cards that are not in the list are deleted."""
    created = await h.make_set(3)
    keep = created.cards[1]

    saved = await h.replace(created.id, [CardDraft(keep.front, keep.back, keep.id)])

    assert [c.id for c in saved.cards] == [keep.id]
    assert saved.card_count == 1 and h.store.sets[created.id].card_count == 1
    assert [c.id for c in h.store.cards_of(created.id)] == [keep.id]
    assert len(h.store.cards) == 1


async def test_an_empty_list_deletes_all_cards(h: FlashcardsHarness) -> None:
    """WEB-24: a student may empty a set."""
    created = await h.make_set(2)

    saved = await h.replace(created.id, [])

    assert saved.cards == () and saved.card_count == 0
    assert h.store.cards == {}


async def test_an_unknown_id_becomes_a_new_card_with_a_fresh_id(
    h: FlashcardsHarness,
) -> None:
    """Safety: an id from nowhere (or another set) never moves a foreign card."""
    mine = await h.make_set(1)
    theirs = await h.make_set(1, owner=h.other_student)
    foreign_id = theirs.cards[0].id

    saved = await h.replace(
        mine.id, [CardDraft("x", "y", foreign_id), CardDraft("z", "w", new_id())]
    )

    assert foreign_id not in {c.id for c in saved.cards}
    assert {c.state for c in saved.cards} == {"new"}
    assert h.store.cards[foreign_id].set_id == theirs.id


async def test_500_cards_are_accepted_and_501_are_refused(
    h: FlashcardsHarness,
) -> None:
    """Plan B10: cards <= 500."""
    created = await h.make_set(1)
    ok = [CardDraft(f"f{i}", f"b{i}") for i in range(500)]

    saved = await h.replace(created.id, ok)
    with pytest.raises(InvalidCardsError):
        await h.replace(created.id, [*ok, CardDraft("one", "more")])

    assert saved.card_count == 500
    assert len(h.store.cards_of(created.id)) == 500


@pytest.mark.parametrize(
    "bad", [CardDraft("", "back"), CardDraft("front", ""), CardDraft("f" * 2001, "b")]
)
async def test_a_bad_card_refuses_the_whole_save(
    h: FlashcardsHarness, bad: CardDraft
) -> None:
    """Plan B10: 1-2000 characters per side; nothing is changed on failure."""
    created = await h.make_set(2)

    with pytest.raises(InvalidCardsError):
        await h.replace(created.id, [CardDraft("fine", "fine"), bad])

    assert [c.front for c in h.store.cards_of(created.id)] == ["front 0", "front 1"]


async def test_the_same_id_twice_is_refused(h: FlashcardsHarness) -> None:
    """WEB-24: a card cannot be in the list twice."""
    created = await h.make_set(1)
    card = created.cards[0]

    with pytest.raises(InvalidCardsError):
        await h.replace(
            created.id,
            [CardDraft("a", "b", card.id), CardDraft("c", "d", card.id)],
        )


async def test_another_students_set_cannot_be_replaced(h: FlashcardsHarness) -> None:
    """Ownership: 404 and the cards stay."""
    created = await h.make_set(2)

    with pytest.raises(FlashcardSetNotFoundError):
        await h.replace(created.id, [CardDraft("x", "y")], owner=h.other_student)

    assert len(h.store.cards_of(created.id)) == 2


async def test_progress_survives_a_text_edit_of_a_learning_card(
    h: FlashcardsHarness,
) -> None:
    """UF-WEB-23: editing a card in learning does not reset its steps."""
    created = await h.make_set(1)
    card = created.cards[0]
    await h.rate(card.id, Rating.MEDIUM)
    due_before = h.store.cards[card.id].due_at
    h.clock.advance(minutes=10)

    await h.replace(created.id, [CardDraft("new text", card.back, card.id)])

    stored = h.store.cards[card.id]
    assert stored.state is CardState.LEARNING and stored.srs.step == 1
    assert stored.due_at == due_before
