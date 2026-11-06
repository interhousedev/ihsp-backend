"""Forced restart: study again today without touching the schedule or the limits."""

from uuid import UUID

from app.modules.flashcards.application.views import StudyNextView
from app.modules.flashcards.domain.errors import (
    FlashcardSetNotFoundError,
    StudyNotFinishedError,
)
from app.modules.flashcards.domain.study import study_day
from app.shared.srs import Rating
from tests.flashcards.conftest import FlashcardsHarness

import pytest


async def _finish(h: FlashcardsHarness, set_id: UUID) -> None:
    """Answer every card with Easy, so all of them leave for days."""
    while (next_card := (await h.study(set_id)).card) is not None:
        await h.rate(next_card.id, Rating.EASY)


async def _restart(h: FlashcardsHarness, set_id: UUID) -> StudyNextView:
    return await h.services.restart_study.execute(
        owner_id=h.student.user_id, set_id=set_id
    )


async def test_restart_offers_every_card_again_after_the_day_is_done(
    h: FlashcardsHarness,
) -> None:
    """The finished screen's button starts a round over the whole set."""
    created = await h.make_set(3)
    await _finish(h, created.id)
    assert (await h.study(created.id)).done_for_today

    view = await _restart(h, created.id)

    assert view.practice
    assert view.practice_remaining == 3
    assert view.card is not None
    assert not view.done_for_today
    assert view.intervals is None


async def test_practice_answers_keep_the_schedule_and_the_daily_counters(
    h: FlashcardsHarness,
) -> None:
    """Even Again on a mature card leaves its state, due date and ease alone."""
    created = await h.make_set(2)
    await _finish(h, created.id)
    before = h.store.cards_of(created.id)
    day = study_day(h.clock.now())
    usage = await h.counters.usage(h.student.user_id, created.id, day)

    view = await _restart(h, created.id)
    assert view.card is not None
    await h.rate(view.card.id, Rating.AGAIN)

    assert h.store.cards_of(created.id) == before
    assert await h.counters.usage(h.student.user_id, created.id, day) == usage


async def test_practice_answers_are_logged_as_practice(h: FlashcardsHarness) -> None:
    """The log says which rows did not schedule anything."""
    created = await h.make_set(1)
    await _finish(h, created.id)
    view = await _restart(h, created.id)
    assert view.card is not None

    await h.rate(view.card.id, Rating.MEDIUM)

    assert [entry.practice for entry in h.store.reviews] == [False, True]


async def test_again_sends_the_card_to_the_end_of_the_round(
    h: FlashcardsHarness,
) -> None:
    """The round ends only when every card was answered without Again."""
    created = await h.make_set(2)
    await _finish(h, created.id)
    first = await _restart(h, created.id)
    assert first.card is not None

    second = await h.rate(first.card.id, Rating.AGAIN)
    assert second.practice_remaining == 2
    assert second.card is not None
    assert second.card.id != first.card.id

    third = await h.rate(second.card.id, Rating.MEDIUM)
    assert third.card is not None
    assert third.card.id == first.card.id
    assert third.practice_remaining == 1

    done = await h.rate(third.card.id, Rating.EASY)
    assert done.done_for_today
    assert not done.practice
    assert done.card is None


async def test_restart_ignores_the_new_card_limit_and_keeps_new_cards_new(
    h: FlashcardsHarness,
) -> None:
    """Cards above today's limit are practiced but stay new for a later day."""
    created = await h.make_set(3)
    await h.services.update_set.execute(
        owner_id=h.student.user_id, set_id=created.id, new_per_day=1
    )
    await _finish(h, created.id)

    view = await _restart(h, created.id)
    assert view.practice_remaining == 3
    while view.card is not None:
        view = await h.rate(view.card.id, Rating.EASY)

    states = [card.state.value for card in h.store.cards_of(created.id)]
    assert sorted(states) == ["new", "new", "review"]


async def test_restart_is_refused_while_cards_are_still_waiting(
    h: FlashcardsHarness,
) -> None:
    """Scheduled work comes first, or a restart would hide it."""
    created = await h.make_set(1)

    with pytest.raises(StudyNotFinishedError):
        await _restart(h, created.id)


async def test_restart_of_someone_elses_set_is_not_found(h: FlashcardsHarness) -> None:
    """Ownership is checked as everywhere else."""
    created = await h.make_set(1, owner=h.other_student)

    with pytest.raises(FlashcardSetNotFoundError):
        await _restart(h, created.id)


async def test_a_card_deleted_during_the_round_is_skipped(h: FlashcardsHarness) -> None:
    """The round holds ids; a deleted id is ignored."""
    created = await h.make_set(2)
    await _finish(h, created.id)
    view = await _restart(h, created.id)
    assert view.card is not None

    await h.services.delete_card.execute(
        owner_id=h.student.user_id, card_id=view.card.id
    )

    after = await h.study(created.id)
    assert after.practice_remaining == 1
    assert after.card is not None
    assert after.card.id != view.card.id


async def test_the_round_ends_with_the_study_day(h: FlashcardsHarness) -> None:
    """Tomorrow the normal schedule is back without any clean-up."""
    created = await h.make_set(2)
    await _finish(h, created.id)
    await _restart(h, created.id)

    h.clock.advance(days=1)

    assert not (await h.study(created.id)).practice
