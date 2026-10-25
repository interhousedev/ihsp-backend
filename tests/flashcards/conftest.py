"""Fixtures of the flashcards tests: the module wired to in-memory fakes."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.flashcards.application.views import SetDetailView, StudyNextView
from app.modules.flashcards.domain.flashcard import CardDraft
from app.modules.flashcards.domain.flashcard_set import SetSource
from app.modules.flashcards.wiring import FlashcardsOverrides, FlashcardsServices, build
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.srs import Rating
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.flashcards.counters import InMemoryDailyCounters
from tests.fakes.flashcards.shares import FakeShares
from tests.fakes.flashcards.uow import FakeFlashcardsStore, fake_uow_factory
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def pairs(count: int) -> list[tuple[str, str]]:
    """(front, back) pairs: ("front 0", "back 0"), ("front 1", "back 1"), ..."""
    return [(f"front {i}", f"back {i}") for i in range(count)]


@dataclass
class FlashcardsHarness:
    """The wired module with every fake reachable for arrangement and assertions."""

    services: FlashcardsServices
    store: FakeFlashcardsStore
    counters: InMemoryDailyCounters
    shares: FakeShares
    clock: FixedClock
    student: Actor
    other_student: Actor
    teacher: Actor

    async def make_set(
        self,
        count: int = 3,
        *,
        owner: Actor | None = None,
        title: str = "Cells",
        source: SetSource = SetSource.MANUAL,
    ) -> SetDetailView:
        """Create a set of `count` new cards for the student (or the given owner)."""
        return await self.services.create_set.execute(
            owner_id=(owner or self.student).user_id,
            title=title,
            cards=pairs(count),
            source=source,
        )

    async def replace(
        self, set_id: UUID, drafts: Sequence[CardDraft], owner: Actor | None = None
    ) -> SetDetailView:
        """Save the full card list as the student (or the given owner)."""
        return await self.services.replace_cards.execute(
            owner_id=(owner or self.student).user_id, set_id=set_id, cards=drafts
        )

    async def study(self, set_id: UUID, owner: Actor | None = None) -> StudyNextView:
        """Ask for the next card as the student (or the given owner)."""
        return await self.services.study_next.execute(
            owner_id=(owner or self.student).user_id, set_id=set_id
        )

    async def rate(
        self,
        card_id: UUID,
        rating: Rating,
        owner: Actor | None = None,
        duration_ms: int | None = None,
    ) -> StudyNextView:
        """Rate a card as the student (or the given owner)."""
        return await self.services.review_card.execute(
            owner_id=(owner or self.student).user_id,
            card_id=card_id,
            rating=rating,
            duration_ms=duration_ms,
        )


@pytest.fixture
def h(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
) -> FlashcardsHarness:
    """The module on in-memory fakes, with a student, another student and a teacher."""
    store, counters, shares = (
        FakeFlashcardsStore(),
        InMemoryDailyCounters(),
        FakeShares(),
    )
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=async_sessionmaker(class_=AsyncSession),
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=noop_outbox_writer,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )
    services = build(
        deps,
        links=shares,
        overrides=FlashcardsOverrides(
            uow_factory=fake_uow_factory(store), counters=counters
        ),
    )
    return FlashcardsHarness(
        services=services,
        store=store,
        counters=counters,
        shares=shares,
        clock=clock,
        student=make_actor(Role.STUDENT),
        other_student=make_actor(Role.STUDENT),
        teacher=make_actor(Role.TEACHER),
    )
