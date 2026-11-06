"""Base hardness, per-card statistics, shuffle, batch add and card edit/delete."""

from uuid import UUID

from app.modules.flashcards.domain.errors import (
    CardNotFoundError,
    InvalidCardsError,
    InvalidSetError,
)
from app.modules.flashcards.domain.flashcard import CardDraft, Hardness, initial_srs
from app.modules.flashcards.domain.flashcard_set import SetSource
from app.shared.srs import START_EASE, CardState, Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


def test_medium_is_the_plain_scheduler_start() -> None:
    """Existing cards (all medium) keep exactly the old behaviour."""
    state = initial_srs(Hardness.MEDIUM)
    assert (state.ease, state.step, state.state) == (START_EASE, 0, CardState.NEW)


def test_hard_starts_with_lower_ease_and_easy_skips_a_step() -> None:
    """Hard cards grow slower; easy cards graduate sooner."""
    assert initial_srs(Hardness.HARD).ease < START_EASE
    easy = initial_srs(Hardness.EASY)
    assert easy.ease > START_EASE
    assert easy.step == 1


async def test_hardness_is_set_on_create_and_changes_the_first_answer(
    h: FlashcardsHarness,
) -> None:
    """Good on a new easy card graduates at once; on medium it stays in learning."""
    created = await h.services.create_set.execute(
        owner_id=h.student.user_id,
        title="T",
        cards=[("a", "1", "easy"), ("b", "2")],
        source=SetSource.MANUAL,
    )
    assert [c.hardness for c in created.cards] == ["easy", "medium"]
    easy, medium = h.store.cards_of(created.id)

    await h.rate(easy.id, Rating.MEDIUM)
    await h.rate(medium.id, Rating.MEDIUM)

    easy_after, medium_after = h.store.cards_of(created.id)
    assert easy_after.state is CardState.REVIEW
    assert medium_after.state is CardState.LEARNING


async def test_an_unknown_hardness_is_a_validation_error(h: FlashcardsHarness) -> None:
    """The batch API takes strings, so the value is checked."""
    with pytest.raises(InvalidCardsError):
        await h.services.create_set.execute(
            owner_id=h.student.user_id,
            title="T",
            cards=[("a", "1", "brutal")],
            source=SetSource.MANUAL,
        )


async def test_editing_hardness_reseeds_only_an_unseen_card(
    h: FlashcardsHarness,
) -> None:
    """A studied card keeps its schedule: its history is worth more than the label."""
    created = await h.make_set(2)
    seen, unseen = h.store.cards_of(created.id)
    await h.rate(seen.id, Rating.EASY)
    seen_srs = h.store.cards_of(created.id)[0].srs

    for card_id in (seen.id, unseen.id):
        await h.services.update_card.execute(
            owner_id=h.student.user_id,
            card_id=card_id,
            front=None,
            back=None,
            hardness=Hardness.HARD,
        )

    seen_after, unseen_after = h.store.cards_of(created.id)
    assert seen_after.hardness is Hardness.HARD
    assert seen_after.srs == seen_srs
    assert unseen_after.srs == initial_srs(Hardness.HARD)


async def test_replace_cards_keeps_hardness_unless_it_is_sent(
    h: FlashcardsHarness,
) -> None:
    """The old web payload (no hardness) must not reset a card to medium."""
    created = await h.services.create_set.execute(
        owner_id=h.student.user_id,
        title="T",
        cards=[("a", "1", "hard"), ("b", "2", "hard")],
        source=SetSource.MANUAL,
    )
    first, second = created.cards

    saved = await h.replace(
        created.id,
        [
            CardDraft("a", "1", first.id),
            CardDraft("b", "2", second.id, Hardness.EASY),
            CardDraft("c", "3", None, Hardness.EASY),
            CardDraft("d", "4"),
        ],
    )

    assert [c.hardness for c in saved.cards] == ["hard", "easy", "easy", "medium"]


async def test_card_stats_count_attempts_by_rating(h: FlashcardsHarness) -> None:
    """Again is incorrect, every other button correct; unseen cards show zeros."""
    created = await h.make_set(2)
    first, second = h.store.cards_of(created.id)
    await h.rate(first.id, Rating.AGAIN)
    h.clock.advance(minutes=5)
    await h.rate(first.id, Rating.HARD)

    stats = await h.services.get_card_stats.execute(
        owner_id=h.student.user_id, set_id=created.id
    )

    by_id = {row.card_id: row for row in stats}
    assert list(by_id) == [first.id, second.id]
    row = by_id[first.id]
    assert (row.attempts, row.correct, row.incorrect) == (2, 1, 1)
    assert row.last_studied_at == h.clock.now()
    empty = by_id[second.id]
    assert (empty.attempts, empty.correct, empty.incorrect) == (0, 0, 0)
    assert empty.last_studied_at is None


async def test_shuffle_changes_the_new_order_but_not_between_two_reads(
    h: FlashcardsHarness,
) -> None:
    """A refresh shows the same card, and some order differs from position order."""
    created = await h.make_set(30)
    updated = await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, shuffle=True
    )
    assert updated.shuffle

    first = await h.study(created.id)
    second = await h.study(created.id)

    assert first.card is not None
    assert second.card is not None
    assert first.card.id == second.card.id
    order: list[UUID] = []
    view = first
    while view.card is not None and len(order) < 20:
        order.append(view.card.id)
        view = await h.rate(view.card.id, Rating.EASY)
    positions = [c.id for c in created.cards][:20]
    assert order != positions


async def test_daily_limit_validation_still_applies(h: FlashcardsHarness) -> None:
    """The settings path keeps the 1-200 rule."""
    created = await h.make_set(1)
    with pytest.raises(InvalidSetError):
        await h.services.update_set.execute(
            owner_id=h.student.user_id, set_id=created.id, new_per_day=0
        )


async def test_delete_card_updates_the_count_and_checks_the_owner(
    h: FlashcardsHarness,
) -> None:
    """A foreign card is "not found"; the owner's card disappears."""
    created = await h.make_set(2)
    card = h.store.cards_of(created.id)[0]

    with pytest.raises(CardNotFoundError):
        await h.services.delete_card.execute(
            owner_id=h.other_student.user_id, card_id=card.id
        )

    await h.services.delete_card.execute(owner_id=h.student.user_id, card_id=card.id)

    assert h.store.sets[created.id].card_count == 1
    assert len(h.store.cards_of(created.id)) == 1


async def test_public_api_exposes_the_settings_and_card_operations(
    h: FlashcardsHarness,
) -> None:
    """The contract the MCP step calls."""
    api = h.services.public
    owner = h.student.user_id
    created = await api.create_set(owner, "T", [("a", "1", "hard")], source="mcp")

    settings = await api.update_set_settings(
        owner, created["id"], shuffle=True, new_per_day=5, reviews_per_day=50
    )
    assert (settings["shuffle"], settings["new_per_day"]) == (True, 5)
    assert settings["reviews_per_day"] == 50

    added = await api.add_cards(owner, created["id"], [("b", "2"), ("c", "3", "easy")])
    assert added["card_count"] == 3

    card_id = added["cards"][1]["id"]
    edited = await api.update_card(owner, card_id, "B", None, hardness="hard")
    assert (edited["front"], edited["hardness"]) == ("B", "hard")

    await api.delete_card(owner, card_id)
    stats = await api.card_stats(owner, created["id"])
    assert len(stats) == 2

    other = await api.create_set(owner, "U", [("z", "9")], source="manual")
    merged = await api.merge_sets(owner, [created["id"], other["id"]], "M")
    assert merged["card_count"] == 3
    assert merged["duplicates_skipped"] == 0
