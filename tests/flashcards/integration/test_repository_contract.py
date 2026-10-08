"""Sets and cards: the same suite runs on the in-memory fake and on PostgreSQL."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.modules.flashcards.domain.flashcard import Flashcard
from app.modules.flashcards.domain.flashcard_set import (
    FlashcardSet,
    SetCounts,
    SetSource,
)
from app.modules.flashcards.infrastructure.uow import SqlFlashcardsUnitOfWork
from app.modules.flashcards.ports.unit_of_work import UowFactory
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from app.shared.srs import CardState, SrsState
from tests.fakes.flashcards.uow import FakeFlashcardsStore, fake_uow_factory

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


@pytest.fixture(params=["fake", "sql"])
def uow_factory(request: pytest.FixtureRequest) -> UowFactory:
    """The unit of work under test: in memory, or SQL on the test transaction."""
    if request.param == "fake":
        return fake_uow_factory(FakeFlashcardsStore())
    sessionmaker: async_sessionmaker[AsyncSession] = request.getfixturevalue(
        "sessionmaker_in_tx"
    )
    return lambda: SqlFlashcardsUnitOfWork(
        sessionmaker, noop_outbox_writer, noop_audit_writer
    )


def make_set(owner: UUID | None = None, **fields: object) -> FlashcardSet:
    """A set entity."""
    return FlashcardSet(
        id=new_id(),
        owner_id=owner or new_id(),
        title="Cells",
        created_at=NOW,
        **fields,  # type: ignore[arg-type]
    )


def make_card(
    set_id: UUID, position: int, srs: SrsState | None = None, text: str = "t"
) -> Flashcard:
    """A card entity."""
    return Flashcard(
        id=new_id(),
        set_id=set_id,
        position=position,
        front=f"front {text}",
        back=f"back {text}",
        srs=srs or SrsState(),
    )


async def test_a_set_round_trips_with_every_field(uow_factory: UowFactory) -> None:
    """README FlashcardSet: all fields are stored and read back."""
    original = make_set()
    copy = make_set(
        description="Chapter 1",
        source=SetSource.COPIED,
        source_chat_id=new_id(),
        copied_from_set_id=original.id,
        new_per_day=5,
        reviews_per_day=50,
        card_count=7,
    )
    async with uow_factory() as uow:
        await uow.sets.add(original)
        await uow.sets.add(copy)
        await uow.commit()

    async with uow_factory() as uow:
        found = await uow.sets.get(copy.id)
        locked = await uow.sets.get_for_update(copy.id)
        missing = await uow.sets.get(new_id())

    assert found == copy and locked == copy
    assert missing is None


async def test_save_writes_the_changed_fields(uow_factory: UowFactory) -> None:
    """Editing a set: title, description, limits and the cached card count."""
    flashcard_set = make_set()
    async with uow_factory() as uow:
        await uow.sets.add(flashcard_set)
        await uow.commit()

    async with uow_factory() as uow:
        loaded = await uow.sets.get_for_update(flashcard_set.id)
        assert loaded is not None
        loaded.title, loaded.description = "Mitosis", "Phases"
        loaded.new_per_day, loaded.reviews_per_day, loaded.card_count = 3, 30, 9
        await uow.sets.save(loaded)
        await uow.commit()

    async with uow_factory() as uow:
        found = await uow.sets.get(flashcard_set.id)
    assert found is not None
    assert (found.title, found.description) == ("Mitosis", "Phases")
    assert (found.new_per_day, found.reviews_per_day, found.card_count) == (3, 30, 9)
    assert found.created_at == NOW


async def test_sets_of_an_owner_come_newest_first(uow_factory: UowFactory) -> None:
    """WEB-22: the list shows the newest set first and only the owner's sets."""
    owner = new_id()
    older = make_set(owner)
    newer = make_set(owner)
    newer.created_at = NOW + timedelta(minutes=1)
    async with uow_factory() as uow:
        await uow.sets.add(older)
        await uow.sets.add(newer)
        await uow.sets.add(make_set())
        await uow.commit()

    async with uow_factory() as uow:
        listed = await uow.sets.list_for_owner(owner)
        nobody = await uow.sets.list_for_owner(new_id())

    assert [s.id for s in listed] == [newer.id, older.id]
    assert nobody == []


async def test_deleting_a_set_deletes_only_its_cards(uow_factory: UowFactory) -> None:
    """WEB-22: cards go with the set; other sets keep theirs."""
    doomed, kept = make_set(), make_set()
    doomed_card = make_card(doomed.id, 0)
    kept_card = make_card(kept.id, 0)
    async with uow_factory() as uow:
        await uow.sets.add(doomed)
        await uow.sets.add(kept)
        await uow.cards.add_many([doomed_card, kept_card])
        await uow.commit()

    async with uow_factory() as uow:
        await uow.sets.delete(doomed.id)
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.sets.get(doomed.id) is None
        assert await uow.cards.get(doomed_card.id) is None
        assert await uow.cards.list_for_set(doomed.id) == []
        assert await uow.sets.get(kept.id) is not None
        assert await uow.cards.get(kept_card.id) is not None


async def test_cards_come_in_position_order(uow_factory: UowFactory) -> None:
    """WEB-24: the order of cards is the saved position."""
    flashcard_set = make_set()
    cards = [make_card(flashcard_set.id, p, text=str(p)) for p in (2, 0, 1)]
    async with uow_factory() as uow:
        await uow.sets.add(flashcard_set)
        await uow.cards.add_many(cards)
        await uow.commit()

    async with uow_factory() as uow:
        listed = await uow.cards.list_for_set(flashcard_set.id)

    assert [c.position for c in listed] == [0, 1, 2]
    assert [c.id for c in listed] == [cards[1].id, cards[2].id, cards[0].id]


async def test_the_scheduling_state_of_a_card_round_trips(
    uow_factory: UowFactory,
) -> None:
    """README Flashcard: state, step, due_at, interval, ease, reps, lapses."""
    flashcard_set = make_set()
    due = NOW + timedelta(days=10)
    card = make_card(
        flashcard_set.id,
        0,
        SrsState(
            state=CardState.RELEARNING,
            step=1,
            due_at=due,
            interval_days=10.5,
            ease=2.25,
            reps=4,
            lapses=2,
        ),
    )
    card.last_reviewed_at = NOW
    async with uow_factory() as uow:
        await uow.sets.add(flashcard_set)
        await uow.cards.add_many([card])
        await uow.commit()

    async with uow_factory() as uow:
        found = await uow.cards.get(card.id)
        locked = await uow.cards.get_for_update(card.id)

    assert found == card and locked == card
    assert found is not None and found.state is CardState.RELEARNING
    assert found.due_at == due and found.last_reviewed_at == NOW


async def test_saving_a_card_and_deleting_cards(uow_factory: UowFactory) -> None:
    """WEB-23/24: a review is saved; missing ids are deleted."""
    flashcard_set = make_set()
    first, second, third = (make_card(flashcard_set.id, p) for p in range(3))
    async with uow_factory() as uow:
        await uow.sets.add(flashcard_set)
        await uow.cards.add_many([first, second, third])
        await uow.commit()

    async with uow_factory() as uow:
        loaded = await uow.cards.get_for_update(first.id)
        assert loaded is not None
        loaded.front = "edited"
        loaded.srs = SrsState(state=CardState.LEARNING, step=1, due_at=NOW)
        await uow.cards.save(loaded)
        await uow.cards.delete_many([second.id, third.id])
        await uow.cards.delete_many([])
        await uow.commit()

    async with uow_factory() as uow:
        listed = await uow.cards.list_for_set(flashcard_set.id)
    assert [c.id for c in listed] == [first.id]
    assert listed[0].front == "edited" and listed[0].state is CardState.LEARNING


async def test_counts_for_sets_split_new_and_due_cards(uow_factory: UowFactory) -> None:
    """WEB-22: new cards, and seen cards due before the bound (per set)."""
    busy, calm, empty = make_set(), make_set(), make_set()
    bound = NOW + timedelta(hours=10)
    review = SrsState(state=CardState.REVIEW, due_at=NOW, interval_days=1.0)
    learning = SrsState(state=CardState.LEARNING, due_at=bound - timedelta(minutes=1))
    later = SrsState(state=CardState.REVIEW, due_at=bound, interval_days=5.0)
    async with uow_factory() as uow:
        for flashcard_set in (busy, calm, empty):
            await uow.sets.add(flashcard_set)
        await uow.cards.add_many(
            [
                make_card(busy.id, 0),
                make_card(busy.id, 1),
                make_card(busy.id, 2, review),
                make_card(busy.id, 3, learning),
                make_card(busy.id, 4, later),
                make_card(calm.id, 0, later),
            ]
        )
        await uow.commit()

    async with uow_factory() as uow:
        counts = await uow.cards.counts_for_sets(
            [busy.id, calm.id, empty.id], due_before=bound
        )
        nothing = await uow.cards.counts_for_sets([], due_before=bound)

    assert counts.get(busy.id) == SetCounts(new=2, due=2)
    assert counts.get(calm.id) == SetCounts(new=0, due=0)
    assert counts.get(empty.id, SetCounts()) == SetCounts()
    assert nothing == {}
