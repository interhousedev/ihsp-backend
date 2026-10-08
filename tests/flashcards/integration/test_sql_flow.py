"""The module on PostgreSQL and Redis: create, study, review, replace, copy, delete."""

from dataclasses import dataclass

from app.modules.flashcards.domain.flashcard import CardDraft
from app.modules.flashcards.domain.flashcard_set import FlashcardSet, SetSource
from app.modules.flashcards.domain.study import study_day
from app.modules.flashcards.infrastructure.uow import SqlFlashcardsUnitOfWork
from app.modules.flashcards.wiring import FlashcardsServices, build
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter
from app.shared.srs import CardState, Rating
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.flashcards.shares import FakeShares
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class SqlWorld:
    """Services on the real SQL unit of work and Redis counters."""

    services: FlashcardsServices
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: FakeRedis
    clock: FixedClock
    shares: FakeShares
    student: Actor
    other: Actor


@pytest.fixture
def world(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> SqlWorld:
    """The flashcards module with no fakes except the links lookup."""
    shares = FakeShares()
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=sessionmaker_in_tx,
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=noop_outbox_writer,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )
    return SqlWorld(
        services=build(deps, links=shares),
        sessionmaker=sessionmaker_in_tx,
        redis=redis,
        clock=clock,
        shares=shares,
        student=Actor(new_id(), frozenset({Role.STUDENT})),
        other=Actor(new_id(), frozenset({Role.STUDENT})),
    )


def cards(count: int) -> list[tuple[str, str]]:
    """(front, back) pairs."""
    return [(f"front {i}", f"back {i}") for i in range(count)]


async def test_study_and_review_work_end_to_end(world: SqlWorld) -> None:
    """WEB-23: SQL state, Redis counters and the limits work together."""
    s = world.services
    created = await s.public.create_set(
        world.student.user_id, "Cells", cards(4), source="manual"
    )
    await s.update_set.execute(
        owner_id=world.student.user_id, set_id=created["id"], new_per_day=2
    )

    first = await s.study_next.execute(
        owner_id=world.student.user_id, set_id=created["id"]
    )
    assert first.card is not None
    after_first = await s.review_card.execute(
        owner_id=world.student.user_id, card_id=first.card.id, rating=Rating.EASY
    )
    assert after_first.card is not None
    after_second = await s.review_card.execute(
        owner_id=world.student.user_id,
        card_id=after_first.card.id,
        rating=Rating.MEDIUM,
    )

    assert first.card.front == "front 0" and after_first.card.front == "front 1"
    assert after_second.done_for_today and after_second.card is None
    key = (
        f"fc:day:{world.student.user_id}:{created['id']}:{study_day(world.clock.now())}"
    )
    assert await world.redis.hgetall(key) == {"new": "2"}  # type: ignore[misc]
    assert await world.redis.ttl(key) > 0
    opened = await s.get_set.execute(
        owner_id=world.student.user_id, set_id=created["id"]
    )
    assert [c.state for c in opened.cards] == ["review", "learning", "new", "new"]
    assert (opened.due_today, opened.new_today) == (1, 0)


async def test_replace_keeps_progress_on_postgres(world: SqlWorld) -> None:
    """WEB-24: kept ids keep their state, new cards are new, missing ids are gone."""
    s, owner = world.services, world.student.user_id
    created = await s.create_set.execute(
        owner_id=owner, title="Cells", cards=cards(3), source=SetSource.MANUAL
    )
    keep, drop, last = created.cards
    await s.review_card.execute(owner_id=owner, card_id=keep.id, rating=Rating.EASY)

    saved = await s.replace_cards.execute(
        owner_id=owner,
        set_id=created.id,
        cards=[
            CardDraft("added", "card"),
            CardDraft("kept and edited", "text", keep.id),
            CardDraft(last.front, last.back, last.id),
        ],
    )

    assert [c.front for c in saved.cards] == ["added", "kept and edited", "front 2"]
    assert [c.state for c in saved.cards] == ["new", "review", "new"]
    assert drop.id not in {c.id for c in saved.cards}
    reread = await s.get_set.execute(owner_id=owner, set_id=created.id)
    assert [(c.position, c.front, c.state) for c in reread.cards] == [
        (0, "added", "new"),
        (1, "kept and edited", "review"),
        (2, "front 2", "new"),
    ]
    assert reread.card_count == 3


async def test_copy_from_share_on_postgres(world: SqlWorld) -> None:
    """SHR-5: the copy has fresh `new` cards and points at the original."""
    s = world.services
    original = await s.create_set.execute(
        owner_id=world.student.user_id,
        title="Shared",
        cards=cards(2),
        source=SetSource.MANUAL,
    )
    await s.review_card.execute(
        owner_id=world.student.user_id, card_id=original.cards[0].id, rating=Rating.EASY
    )
    world.shares.add("slug", "flashcard_set", original.id)

    copy = await s.copy_from_share.execute(actor=world.other, share_slug="slug")

    assert copy.source == "copied" and copy.id != original.id
    assert {c.state for c in copy.cards} == {"new"}
    mine = await s.list_sets.execute(owner_id=world.other.user_id)
    assert [item.id for item in mine] == [copy.id]
    async with SqlFlashcardsUnitOfWork(
        world.sessionmaker, noop_outbox_writer, noop_audit_writer
    ) as uow:
        stored = await uow.sets.get(copy.id)
    assert stored is not None and stored.copied_from_set_id == original.id


async def test_deleting_the_original_keeps_the_copy(world: SqlWorld) -> None:
    """SHR-5: `copied_from_set_id` becomes empty, cards of the copy stay."""
    s = world.services
    original = await s.create_set.execute(
        owner_id=world.student.user_id,
        title="Shared",
        cards=cards(2),
        source=SetSource.MANUAL,
    )
    world.shares.add("slug", "flashcard_set", original.id)
    copy = await s.copy_from_share.execute(actor=world.other, share_slug="slug")

    await s.delete_set.execute(owner_id=world.student.user_id, set_id=original.id)

    reread = await s.get_set.execute(owner_id=world.other.user_id, set_id=copy.id)
    assert len(reread.cards) == 2
    async with SqlFlashcardsUnitOfWork(
        world.sessionmaker, noop_outbox_writer, noop_audit_writer
    ) as uow:
        stored = await uow.sets.get(copy.id)
        assert stored is not None and stored.copied_from_set_id is None
        assert await uow.cards.list_for_set(original.id) == []


async def test_work_that_is_not_committed_is_rolled_back(world: SqlWorld) -> None:
    """Transactions: leaving the unit of work without commit() saves nothing."""
    flashcard_set = FlashcardSet(
        id=new_id(),
        owner_id=world.student.user_id,
        title="Lost",
        created_at=world.clock.now(),
    )
    async with SqlFlashcardsUnitOfWork(
        world.sessionmaker, noop_outbox_writer, noop_audit_writer
    ) as uow:
        await uow.sets.add(flashcard_set)

    async with SqlFlashcardsUnitOfWork(
        world.sessionmaker, noop_outbox_writer, noop_audit_writer
    ) as uow:
        assert await uow.sets.get(flashcard_set.id) is None


async def test_the_state_columns_accept_every_card_state(world: SqlWorld) -> None:
    """README Flashcard: new, learning, review and relearning are all storable."""
    s, owner = world.services, world.student.user_id
    created = await s.create_set.execute(
        owner_id=owner, title="States", cards=cards(4), source=SetSource.MANUAL
    )
    a, b, c, _ = (card.id for card in created.cards)
    await s.review_card.execute(owner_id=owner, card_id=a, rating=Rating.MEDIUM)
    await s.review_card.execute(owner_id=owner, card_id=b, rating=Rating.EASY)
    world.clock.advance(days=4)
    await s.review_card.execute(owner_id=owner, card_id=b, rating=Rating.AGAIN)
    await s.review_card.execute(owner_id=owner, card_id=c, rating=Rating.EASY)

    opened = await s.get_set.execute(owner_id=owner, set_id=created.id)

    assert {card.state for card in opened.cards} == {
        CardState.NEW.value,
        CardState.LEARNING.value,
        CardState.REVIEW.value,
        CardState.RELEARNING.value,
    }
