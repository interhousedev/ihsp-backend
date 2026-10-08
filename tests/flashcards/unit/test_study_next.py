"""WEB-23, UF-WEB-22: the card to study next, the labels and the daily limits."""

from app.modules.flashcards.domain.errors import FlashcardSetNotFoundError
from app.shared.ids import new_id
from app.shared.srs import Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def test_a_fresh_set_offers_its_first_card_with_the_button_labels(
    h: FlashcardsHarness,
) -> None:
    """UF-WEB-22: front and back of the first card, "1m / 1m / 10m / 4d"."""
    created = await h.make_set(3)

    study = await h.study(created.id)

    assert study.set_id == created.id and not study.done_for_today
    assert study.card is not None
    assert (study.card.id, study.card.front, study.card.back, study.card.state) == (
        created.cards[0].id,
        "front 0",
        "back 0",
        "new",
    )
    assert study.intervals is not None
    assert (
        study.intervals.again,
        study.intervals.hard,
        study.intervals.medium,
        study.intervals.easy,
    ) == ("1m", "1m", "10m", "4d")
    assert (study.counts.learning, study.counts.review, study.counts.new) == (0, 0, 3)


async def test_order_is_due_learning_then_reviews_then_new_cards(
    h: FlashcardsHarness,
) -> None:
    """WEB-23: due learning cards, then reviews due today, then new cards."""
    created = await h.make_set(4)
    a, b, c, _ = (card.id for card in created.cards)
    await h.rate(a, Rating.MEDIUM)  # learning, due in 10 minutes
    await h.rate(b, Rating.EASY)  # review, due in 4 days

    waiting = await h.study(created.id)
    h.clock.advance(minutes=10)
    learning_due = await h.study(created.id)
    await h.rate(a, Rating.EASY)  # review, due 4 days after this moment
    h.clock.advance(days=4, minutes=1)
    review_due = await h.study(created.id)

    assert waiting.card is not None and waiting.card.id == c  # nothing else is due
    assert (waiting.counts.learning, waiting.counts.new) == (1, 2)
    assert learning_due.card is not None and learning_due.card.id == a
    assert learning_due.card.state == "learning"
    assert review_due.card is not None and review_due.card.id == b
    assert review_due.card.state == "review"
    assert (review_due.counts.review, review_due.counts.new) == (2, 2)


async def test_the_21st_new_card_is_not_offered_today(h: FlashcardsHarness) -> None:
    """WEB-23: with 20 new cards per day the 21st waits until tomorrow."""
    created = await h.make_set(25)
    for _ in range(20):
        study = await h.study(created.id)
        assert study.card is not None
        await h.rate(study.card.id, Rating.EASY)

    blocked = await h.study(created.id)
    h.clock.advance(hours=24)
    tomorrow = await h.study(created.id)

    assert blocked.card is None and blocked.intervals is None
    assert blocked.done_for_today
    assert (blocked.counts.learning, blocked.counts.review, blocked.counts.new) == (
        0,
        0,
        0,
    )
    assert tomorrow.card is not None and tomorrow.card.id == created.cards[20].id
    assert tomorrow.counts.new == 5


async def test_a_lower_new_per_day_limit_applies_at_once(h: FlashcardsHarness) -> None:
    """WEB-23: the limit is editable per set."""
    created = await h.make_set(5)
    await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, new_per_day=2
    )
    for _ in range(2):
        study = await h.study(created.id)
        assert study.card is not None
        await h.rate(study.card.id, Rating.EASY)

    study = await h.study(created.id)

    assert study.done_for_today and study.card is None


async def test_the_review_limit_stops_reviews_but_new_cards_follow(
    h: FlashcardsHarness,
) -> None:
    """WEB-23: with 1 review per day the second due review waits."""
    created = await h.make_set(3)
    first, second, third = (card.id for card in created.cards)
    await h.rate(first, Rating.EASY)
    await h.rate(second, Rating.EASY)
    h.clock.advance(days=4, minutes=1)
    await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, reviews_per_day=1
    )

    before = await h.study(created.id)
    assert before.card is not None
    after = await h.rate(before.card.id, Rating.MEDIUM)

    assert before.card.id == first and before.counts.review == 1
    assert after.card is not None and after.card.id == third
    assert after.card.state == "new"
    assert (after.counts.review, after.counts.new) == (0, 1)


async def test_learning_cards_are_not_limited(h: FlashcardsHarness) -> None:
    """WEB-23: a card in learning comes back even after the new-card limit."""
    created = await h.make_set(3)
    await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, new_per_day=1
    )
    await h.rate(created.cards[0].id, Rating.MEDIUM)
    h.clock.advance(minutes=10)

    study = await h.study(created.id)

    assert study.card is not None and study.card.id == created.cards[0].id
    assert study.counts.new == 0


async def test_nothing_due_means_done_for_today(h: FlashcardsHarness) -> None:
    """UF-WEB-22: the session ends with a summary when nothing is due."""
    created = await h.make_set(1)
    await h.rate(created.cards[0].id, Rating.EASY)

    study = await h.study(created.id)

    assert study.card is None and study.intervals is None and study.done_for_today
    assert study.set_id == created.id


async def test_an_empty_set_is_done_for_today(h: FlashcardsHarness) -> None:
    """UF-WEB-22: no cards, nothing to study."""
    created = await h.make_set(0)

    assert (await h.study(created.id)).done_for_today


async def test_another_students_set_cannot_be_studied(h: FlashcardsHarness) -> None:
    """Ownership: 404."""
    created = await h.make_set(1)

    with pytest.raises(FlashcardSetNotFoundError):
        await h.study(created.id, owner=h.other_student)
    with pytest.raises(FlashcardSetNotFoundError):
        await h.study(new_id())
