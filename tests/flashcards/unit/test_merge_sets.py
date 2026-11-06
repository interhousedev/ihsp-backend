"""Merging sets: a new set of copied cards; the sources stay; duplicates collapse."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.flashcards.application.merge_sets import MergedSetView
from app.modules.flashcards.application.views import SetDetailView
from app.modules.flashcards.domain.errors import (
    FlashcardSetNotFoundError,
    InvalidCardsError,
    InvalidMergeError,
)
from app.modules.flashcards.domain.flashcard import CardInput, Hardness
from app.modules.flashcards.domain.flashcard_set import SetSource
from app.shared.actor import Actor
from app.shared.srs import CardState, Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def _set(
    h: FlashcardsHarness, cards: Sequence[CardInput], owner: Actor | None = None
) -> SetDetailView:
    return await h.services.create_set.execute(
        owner_id=(owner or h.student).user_id,
        title="Set",
        cards=cards,
        source=SetSource.MANUAL,
    )


async def _merge(h: FlashcardsHarness, set_ids: list[UUID]) -> MergedSetView:
    return await h.services.merge_sets.execute(
        owner_id=h.student.user_id, set_ids=set_ids, title="Merged"
    )


async def test_merge_copies_the_cards_in_order_and_keeps_the_sources(
    h: FlashcardsHarness,
) -> None:
    """The new set follows the order of the selection."""
    one = await _set(h, [("a", "1"), ("b", "2")])
    two = await _set(h, [("c", "3")])

    merged = await _merge(h, [two.id, one.id])

    assert [c.front for c in merged.set.cards] == ["c", "a", "b"]
    assert [c.position for c in merged.set.cards] == [0, 1, 2]
    assert merged.set.title == "Merged"
    assert merged.set.source == "copied"
    assert merged.duplicates_skipped == 0
    assert h.store.sets[one.id].card_count == 2
    assert len(h.store.cards_of(two.id)) == 1


async def test_exact_duplicates_are_dropped_ignoring_case_and_spaces(
    h: FlashcardsHarness,
) -> None:
    """The first copy wins and the number of skipped cards is reported."""
    one = await _set(h, [("Cell  wall", "Rigid"), ("b", "2")])
    two = await _set(h, [("cell wall", " rigid "), ("c", "3")])

    merged = await _merge(h, [one.id, two.id])

    assert [c.front for c in merged.set.cards] == ["Cell  wall", "b", "c"]
    assert merged.duplicates_skipped == 1


async def test_the_same_question_with_another_answer_is_kept(
    h: FlashcardsHarness,
) -> None:
    """Different answers are different knowledge; only the student can choose."""
    one = await _set(h, [("bank", "river side")])
    two = await _set(h, [("bank", "money")])

    merged = await _merge(h, [one.id, two.id])

    assert len(merged.set.cards) == 2
    assert merged.duplicates_skipped == 0


async def test_the_copies_start_fresh_but_keep_their_hardness(
    h: FlashcardsHarness,
) -> None:
    """Progress belongs to the source card; the base hardness describes the text."""
    one = await _set(h, [("a", "1", "hard")])
    card = h.store.cards_of(one.id)[0]
    await h.rate(card.id, Rating.EASY)
    two = await _set(h, [("b", "2")])

    merged = await _merge(h, [one.id, two.id])

    copied = h.store.cards_of(merged.set.id)[0]
    assert copied.id != card.id
    assert copied.state is CardState.NEW
    assert copied.hardness is Hardness.HARD


async def test_a_merge_needs_two_different_sets(h: FlashcardsHarness) -> None:
    """A repeated id does not count twice."""
    one = await _set(h, [("a", "1")])

    with pytest.raises(InvalidMergeError):
        await _merge(h, [one.id, one.id])


async def test_someone_elses_set_cannot_be_merged(h: FlashcardsHarness) -> None:
    """A foreign id reads as "not found" and nothing is created."""
    mine = await _set(h, [("a", "1")])
    theirs = await _set(h, [("b", "2")], owner=h.other_student)
    sets_before = len(h.store.sets)

    with pytest.raises(FlashcardSetNotFoundError):
        await _merge(h, [mine.id, theirs.id])

    assert len(h.store.sets) == sets_before


async def test_the_result_may_not_exceed_the_set_limit(h: FlashcardsHarness) -> None:
    """500 cards at most, counted after duplicates are removed."""
    one = await _set(h, [(f"a{i}", "x") for i in range(300)])
    two = await _set(h, [(f"b{i}", "x") for i in range(201)])

    with pytest.raises(InvalidCardsError):
        await _merge(h, [one.id, two.id])
