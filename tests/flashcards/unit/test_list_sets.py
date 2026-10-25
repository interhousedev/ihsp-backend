"""WEB-22, WEB-23: the list of sets with `due_today` and `new_today`."""

from app.modules.flashcards.domain.flashcard_set import SetSource
from app.shared.srs import Rating
from tests.flashcards.conftest import FlashcardsHarness


async def test_only_my_sets_are_listed_newest_first(h: FlashcardsHarness) -> None:
    """WEB-22: another student's sets are not visible."""
    first = await h.make_set(1, title="First")
    h.clock.advance(minutes=5)
    second = await h.make_set(1, title="Second", source=SetSource.AI)
    await h.make_set(1, title="Not mine", owner=h.other_student)

    listed = await h.services.list_sets.execute(owner_id=h.student.user_id)

    assert [s.id for s in listed] == [second.id, first.id]
    assert [s.source for s in listed] == ["ai", "manual"]
    assert listed[0].card_count == 1 and listed[0].description is None


async def test_a_set_without_progress_has_only_new_cards(h: FlashcardsHarness) -> None:
    """WEB-22: new cards are offered, nothing is due."""
    await h.make_set(3)

    (item,) = await h.services.list_sets.execute(owner_id=h.student.user_id)

    assert (item.due_today, item.new_today) == (0, 3)


async def test_due_today_counts_seen_cards_due_before_the_day_ends(
    h: FlashcardsHarness,
) -> None:
    """WEB-22: `due_today` = cards that are not new and due by the end of today."""
    created = await h.make_set(4)
    ids = [c.id for c in created.cards]
    await h.rate(ids[0], Rating.MEDIUM)  # learning, due in 10 minutes: today
    await h.rate(ids[1], Rating.EASY)  # review, due in 4 days: not today

    (item,) = await h.services.list_sets.execute(owner_id=h.student.user_id)

    assert item.due_today == 1
    assert item.new_today == 2


async def test_new_today_is_what_is_left_of_the_daily_limit(
    h: FlashcardsHarness,
) -> None:
    """WEB-22: min(new cards, new_per_day - introduced today)."""
    created = await h.make_set(6)
    await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, new_per_day=3
    )
    await h.rate(created.cards[0].id, Rating.EASY)
    await h.rate(created.cards[1].id, Rating.EASY)

    (item,) = await h.services.list_sets.execute(owner_id=h.student.user_id)

    assert item.new_today == 1  # 3 per day - 2 introduced; 4 new cards remain


async def test_new_today_is_full_again_the_next_day(h: FlashcardsHarness) -> None:
    """WEB-23: the limit counts per study day."""
    created = await h.make_set(6)
    await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, new_per_day=2
    )
    await h.rate(created.cards[0].id, Rating.EASY)
    await h.rate(created.cards[1].id, Rating.EASY)
    (today,) = await h.services.list_sets.execute(owner_id=h.student.user_id)

    h.clock.advance(hours=24)
    (tomorrow,) = await h.services.list_sets.execute(owner_id=h.student.user_id)

    assert (today.new_today, tomorrow.new_today) == (0, 2)


async def test_a_student_without_sets_gets_an_empty_list(h: FlashcardsHarness) -> None:
    """WEB-22: nothing to show."""
    assert await h.services.list_sets.execute(owner_id=h.student.user_id) == []


# - - - New / Learning / Due as Anki shows them - - -


async def test_a_fresh_set_shows_only_new_cards(h: FlashcardsHarness) -> None:
    """WEB-22: Anki's deck list: New 3, Learn 0, Due 0."""
    await h.make_set(3)

    (item,) = await h.services.list_sets.execute(owner_id=h.student.user_id)

    assert (item.new_count, item.learning_count, item.due_count) == (3, 0, 0)


async def test_learning_cards_are_counted_until_the_day_ends(
    h: FlashcardsHarness,
) -> None:
    """WEB-23: a card in a 10-minute step is "learning"; one due in 4 days is not."""
    created = await h.make_set(3)
    await h.rate(created.cards[0].id, Rating.MEDIUM)  # learning, due in 10 minutes
    await h.rate(created.cards[1].id, Rating.EASY)  # review, due in 4 days

    (item,) = await h.services.list_sets.execute(owner_id=h.student.user_id)

    assert (item.new_count, item.learning_count, item.due_count) == (1, 1, 0)


async def test_review_cards_due_today_are_counted_as_due(
    h: FlashcardsHarness,
) -> None:
    """WEB-23: a review card whose day has come is "due" (green in Anki)."""
    created = await h.make_set(2)
    await h.rate(created.cards[0].id, Rating.EASY)
    await h.rate(created.cards[1].id, Rating.EASY)
    h.clock.advance(days=4)

    (item,) = await h.services.list_sets.execute(owner_id=h.student.user_id)

    assert (item.new_count, item.learning_count, item.due_count) == (0, 0, 2)


async def test_due_count_stops_at_the_reviews_per_day_limit(
    h: FlashcardsHarness,
) -> None:
    """WEB-23: with 2 reviews per day, 5 due cards show as 2, then fewer once done."""
    created = await h.make_set(5)
    for card in created.cards:
        await h.rate(card.id, Rating.EASY)
    await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, reviews_per_day=2
    )
    h.clock.advance(days=4)
    (before,) = await h.services.list_sets.execute(owner_id=h.student.user_id)

    await h.rate(created.cards[0].id, Rating.MEDIUM)
    (after,) = await h.services.list_sets.execute(owner_id=h.student.user_id)

    assert (before.due_count, after.due_count) == (2, 1)


async def test_the_list_numbers_equal_the_study_queue_sizes(
    h: FlashcardsHarness,
) -> None:
    """WEB-23: the deck list and the study screen show the same three numbers."""
    created = await h.make_set(6)
    await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, new_per_day=4
    )
    await h.rate(created.cards[0].id, Rating.EASY)
    await h.rate(created.cards[1].id, Rating.MEDIUM)
    h.clock.advance(days=5)

    (item,) = await h.services.list_sets.execute(owner_id=h.student.user_id)
    detail = await h.services.get_set.execute(
        owner_id=h.student.user_id, set_id=created.id
    )
    study = await h.study(created.id)

    expected = (study.counts.new, study.counts.learning, study.counts.review)
    assert (item.new_count, item.learning_count, item.due_count) == expected
    assert (detail.new_count, detail.learning_count, detail.due_count) == expected
