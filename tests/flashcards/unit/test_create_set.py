"""WEB-22: creating a set (by hand, by the assistant, through MCP)."""

from app.modules.flashcards.domain.errors import InvalidCardsError, InvalidSetError
from app.modules.flashcards.domain.flashcard_set import SetSource
from app.shared.ids import new_id
from app.shared.srs import CardState
from tests.flashcards.conftest import FlashcardsHarness, pairs

import pytest


async def test_a_new_set_has_new_cards_in_list_order(h: FlashcardsHarness) -> None:
    """WEB-22: cards are saved with positions 0..n-1 in the state `new`."""
    created = await h.services.create_set.execute(
        owner_id=h.student.user_id,
        title="Cell biology",
        description="Chapter 1",
        cards=pairs(3),
        source=SetSource.MANUAL,
    )

    assert (created.title, created.description, created.source) == (
        "Cell biology",
        "Chapter 1",
        "manual",
    )
    assert created.card_count == 3
    assert [c.front for c in created.cards] == ["front 0", "front 1", "front 2"]
    assert [c.position for c in created.cards] == [0, 1, 2]
    assert {c.state for c in created.cards} == {"new"}
    assert {c.due_at for c in created.cards} == {None}
    assert (created.new_per_day, created.reviews_per_day) == (20, 200)
    assert (created.due_today, created.new_today) == (0, 3)
    stored = h.store.cards_of(created.id)
    assert all(c.state is CardState.NEW for c in stored)
    assert h.store.commits == 1


async def test_the_source_and_the_chat_are_kept(h: FlashcardsHarness) -> None:
    """WEB-22: sets made by the assistant remember the chat; MCP sets are marked."""
    chat_id = new_id()

    ai = await h.services.create_set.execute(
        owner_id=h.student.user_id,
        title="From chat",
        cards=pairs(1),
        source=SetSource.AI,
        source_chat_id=chat_id,
    )
    mcp = await h.make_set(1, source=SetSource.MCP)

    assert h.store.sets[ai.id].source_chat_id == chat_id
    assert (ai.source, mcp.source) == ("ai", "mcp")
    assert h.store.sets[mcp.id].owner_id == h.student.user_id


async def test_title_and_description_are_cleaned(h: FlashcardsHarness) -> None:
    """WEB-22: whitespace is trimmed; a blank description is none."""
    created = await h.services.create_set.execute(
        owner_id=h.student.user_id,
        title="  Cell   biology ",
        description="   ",
        cards=pairs(1),
        source=SetSource.MANUAL,
    )

    assert (created.title, created.description) == ("Cell biology", None)


async def test_500_cards_are_accepted(h: FlashcardsHarness) -> None:
    """Plan B10: at most 500 cards."""
    created = await h.make_set(500)

    assert created.card_count == 500
    assert len(h.store.cards_of(created.id)) == 500


async def test_501_cards_are_refused_and_nothing_is_saved(
    h: FlashcardsHarness,
) -> None:
    """Plan B10: cards <= 500."""
    with pytest.raises(InvalidCardsError):
        await h.make_set(501)

    assert h.store.sets == {} and h.store.cards == {}


@pytest.mark.parametrize(
    "bad_cards",
    [[("", "back")], [("front", "")], [("f" * 2001, "back")], [("ok", "b" * 2001)]],
)
async def test_a_card_side_must_have_1_to_2000_characters(
    h: FlashcardsHarness, bad_cards: list[tuple[str, str]]
) -> None:
    """Plan B10: front/back 1-2000 characters; one bad card refuses the set."""
    with pytest.raises(InvalidCardsError):
        await h.services.create_set.execute(
            owner_id=h.student.user_id,
            title="Bad",
            cards=[*pairs(2), *bad_cards],
            source=SetSource.MANUAL,
        )

    assert h.store.sets == {}


async def test_a_set_without_cards_is_allowed(h: FlashcardsHarness) -> None:
    """UF-WEB-23: a student may create the set first and add cards later."""
    created = await h.make_set(0)

    assert (created.card_count, created.cards) == (0, ())


async def test_a_blank_title_is_refused(h: FlashcardsHarness) -> None:
    """WEB-22: a set needs a title."""
    with pytest.raises(InvalidSetError):
        await h.make_set(1, title="   ")

    assert h.store.sets == {}
