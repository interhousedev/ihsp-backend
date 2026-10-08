"""WEB-23: rating a card moves it through the states and counts against the limits."""

from datetime import timedelta

from app.modules.flashcards.domain.errors import CardNotFoundError
from app.modules.flashcards.domain.study import study_day
from app.shared.ids import new_id
from app.shared.srs import CardState, Rating, SrsState, review
from tests.flashcards.conftest import FlashcardsHarness

import pytest


@pytest.mark.parametrize(
    ("rating", "state", "step", "due_in"),
    [
        (Rating.AGAIN, CardState.LEARNING, 0, timedelta(minutes=1)),
        (Rating.HARD, CardState.LEARNING, 0, timedelta(minutes=1)),
        (Rating.MEDIUM, CardState.LEARNING, 1, timedelta(minutes=10)),
        (Rating.EASY, CardState.REVIEW, 0, timedelta(days=4)),
    ],
)
async def test_a_new_card_moves_as_the_scheduler_says(
    h: FlashcardsHarness,
    rating: Rating,
    state: CardState,
    step: int,
    due_in: timedelta,
) -> None:
    """WEB-23: learning steps of 1 and 10 minutes; Easy goes to review with 4 days."""
    created = await h.make_set(1)
    card_id = created.cards[0].id

    await h.rate(card_id, rating)

    stored = h.store.cards[card_id]
    assert (stored.state, stored.srs.step) == (state, step)
    assert stored.due_at == h.clock.now() + due_in
    assert stored.last_reviewed_at == h.clock.now()


async def test_a_review_card_follows_the_scheduler_over_time(
    h: FlashcardsHarness,
) -> None:
    """WEB-23: Medium on a 4-day review gives 4 x ease 2.5 = 10 days."""
    created = await h.make_set(1)
    card_id = created.cards[0].id
    await h.rate(card_id, Rating.EASY)
    h.clock.advance(days=4)
    expected = review(h.store.cards[card_id].srs, Rating.MEDIUM, h.clock.now())

    await h.rate(card_id, Rating.MEDIUM)

    stored = h.store.cards[card_id]
    assert stored.srs == expected
    assert stored.srs.interval_days == pytest.approx(10.0)
    assert stored.due_at == h.clock.now() + timedelta(days=10)
    assert stored.srs.reps == 2


async def test_again_on_a_review_card_is_a_lapse(h: FlashcardsHarness) -> None:
    """WEB-23: Again -> relearning in 10 minutes, ease -0.20, one lapse."""
    created = await h.make_set(1)
    card_id = created.cards[0].id
    await h.rate(card_id, Rating.EASY)
    h.clock.advance(days=4)

    await h.rate(card_id, Rating.AGAIN)

    stored = h.store.cards[card_id]
    assert stored.state is CardState.RELEARNING and stored.srs.lapses == 1
    assert stored.srs.ease == pytest.approx(2.3)
    assert stored.due_at == h.clock.now() + timedelta(minutes=10)


async def test_the_answer_is_the_next_card_to_study(h: FlashcardsHarness) -> None:
    """UF-WEB-22: the response is StudyNext for the following card."""
    created = await h.make_set(2)

    after = await h.rate(created.cards[0].id, Rating.AGAIN)

    assert after.set_id == created.id and not after.done_for_today
    assert after.card is not None and after.card.id == created.cards[1].id
    assert (after.counts.learning, after.counts.new) == (1, 1)


async def test_the_last_card_answered_ends_the_session(h: FlashcardsHarness) -> None:
    """UF-WEB-22: nothing left today."""
    created = await h.make_set(1)

    after = await h.rate(created.cards[0].id, Rating.EASY)

    assert after.card is None and after.done_for_today and after.intervals is None


async def test_first_answers_count_as_new_and_reviews_as_reviews(
    h: FlashcardsHarness,
) -> None:
    """WEB-23: counters `new` and `review` per user, set and day; learning is free."""
    created = await h.make_set(2)
    first, second = created.cards[0].id, created.cards[1].id
    day = study_day(h.clock.now())

    await h.rate(first, Rating.MEDIUM)  # new -> learning
    await h.rate(second, Rating.EASY)  # new -> review
    after_new = await h.counters.usage(h.student.user_id, created.id, day)
    h.clock.advance(minutes=10)
    await h.rate(first, Rating.EASY)  # learning -> review: not counted
    after_learning = await h.counters.usage(h.student.user_id, created.id, day)
    h.clock.advance(days=5)
    await h.rate(second, Rating.MEDIUM)  # review -> review
    after_review = await h.counters.usage(
        h.student.user_id, created.id, study_day(h.clock.now())
    )

    assert (after_new.new, after_new.review) == (2, 0)
    assert (after_learning.new, after_learning.review) == (2, 0)
    assert (after_review.new, after_review.review) == (0, 1)


async def test_another_students_card_cannot_be_rated(h: FlashcardsHarness) -> None:
    """Ownership: 404 and the card is unchanged."""
    created = await h.make_set(1)
    card_id = created.cards[0].id

    with pytest.raises(CardNotFoundError):
        await h.rate(card_id, Rating.EASY, owner=h.other_student)

    assert h.store.cards[card_id].srs == SrsState()
    assert h.store.commits == 1  # only the creation


async def test_an_unknown_card_is_not_found(h: FlashcardsHarness) -> None:
    """Ownership: unknown ids give 404."""
    with pytest.raises(CardNotFoundError) as raised:
        await h.rate(new_id(), Rating.EASY)

    assert raised.value.code == "flashcards/card-not-found"
