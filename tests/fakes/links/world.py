"""A fully wired links module on in-memory fakes, for unit and HTTP tests."""

import random
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.links.wiring import LinksOverrides, LinksServices, build
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.factories import make_actor
from tests.fakes.links.ai import FakeAi, FakeFlashcards, FakeNotebooks
from tests.fakes.links.files import FakeFiles
from tests.fakes.links.identity import FakeIdentity
from tests.fakes.links.schedule import FakeSchedule
from tests.fakes.links.titles import FakeTitleFetcher
from tests.fakes.links.uow import FakeUowFactory
from tests.fakes.tasks import FakeTaskKicker

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class LinksWorld:
    """Services plus the fakes they run on and a few ready-made people."""

    services: LinksServices
    uow: FakeUowFactory
    files: FakeFiles
    schedule: FakeSchedule
    identity: FakeIdentity
    ai: FakeAi
    flashcards: FakeFlashcards
    notebooks: FakeNotebooks
    titles: FakeTitleFetcher
    redis: Redis
    kicker: FakeTaskKicker
    people: dict[str, Actor] = field(default_factory=dict)

    def person(self, name: str, *roles: Role, last_name: str | None = None) -> Actor:
        """Create a user known to the identity fake and return their Actor."""
        user = self.identity.add(name, last_name or name.upper())
        actor = make_actor(*(roles or (Role.STUDENT,)), user_id=user.id)
        self.people[name] = actor
        return actor

    def user_id(self, name: str) -> UUID:
        """Return the id of a person created by person()."""
        return self.people[name].user_id


def build_world(
    *,
    settings: Settings,
    clock: Clock,
    redis: Redis,
    i18n: I18nCore,
    sessionmaker: async_sessionmaker[AsyncSession],
    seed: int = 7,
) -> LinksWorld:
    """Wire the module on fakes; Redis and the page renderer are real."""
    files, schedule, identity = FakeFiles(), FakeSchedule(), FakeIdentity()
    ai, flashcards, titles = FakeAi(), FakeFlashcards(), FakeTitleFetcher()
    notebooks = FakeNotebooks()
    uow = FakeUowFactory()
    kicker = FakeTaskKicker()
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=sessionmaker,
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=noop_outbox_writer,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )
    services = build(
        deps,
        files=files,
        schedule=schedule,
        identity=identity,
        ai=ai,
        flashcards=flashcards,
        notebooks=notebooks,
        overrides=LinksOverrides(
            uow_factory=uow,
            title_fetcher=titles,
            rng=random.Random(seed),
            blocked_domains=frozenset({"blocked.example"}),
        ),
    )
    return LinksWorld(
        services,
        uow,
        files,
        schedule,
        identity,
        ai,
        flashcards,
        notebooks,
        titles,
        redis,
        kicker,
    )
