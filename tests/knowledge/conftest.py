"""Fixtures of the knowledge tests: the module on in-memory fakes or on PostgreSQL."""

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.ai.infrastructure.fake_embeddings import FakeEmbeddingGateway
from app.modules.knowledge.infrastructure.uow import SqlKnowledgeUnitOfWork
from app.modules.knowledge.wiring import KnowledgeOverrides, KnowledgeServices, build
from app.modules.vectors.application.embed_query import EmbedQuery
from app.modules.vectors.application.embed_texts import EmbedTexts
from app.modules.vectors.application.vector_index import VectorIndex
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.embeddings import EmbeddingIndex
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.knowledge.uow import FakeKnowledgeStore, fake_uow_factory
from tests.fakes.tasks import FakeTaskKicker
from tests.fakes.vectors.index import make_index
from tests.fakes.vectors.stores import (
    FakeEmbeddingStore,
    FakeQueryCache,
    FakeTokenBudget,
)

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class KnowledgeHarness:
    """The wired module and the pieces tests arrange and assert on."""

    services: KnowledgeServices
    index: EmbeddingIndex
    gateway: FakeEmbeddingGateway
    admin: Actor
    store: FakeKnowledgeStore | None = None

    async def add(self, key: str, value: str, **fields: object) -> str:
        """Create an entry as the admin; return its key."""
        entry = await self.services.create_entry.execute(
            self.admin.user_id, key=key, value=value, **fields  # type: ignore[arg-type]
        )
        return entry.key


def _deps(
    settings: Settings,
    clock: FixedClock,
    redis: FakeRedis,
    i18n: I18nCore,
    kicker: FakeTaskKicker,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> ModuleDeps:
    return ModuleDeps(
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


@pytest.fixture
def fake_h(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
) -> KnowledgeHarness:
    """The module on in-memory fakes, vectors included."""
    vectors = FakeEmbeddingStore()
    gateway = FakeEmbeddingGateway()
    index = VectorIndex(
        gateway,
        EmbedTexts(gateway=gateway, store=vectors, budget=FakeTokenBudget()),
        EmbedQuery(
            gateway=gateway,
            cache=FakeQueryCache(),
            budget=FakeTokenBudget(),
            timeout_seconds=2.0,
            cache_seconds=60,
        ),
    )
    store = FakeKnowledgeStore()
    store.vectors = vectors.rows
    services = build(
        _deps(
            settings,
            clock,
            redis,
            i18n,
            kicker,
            async_sessionmaker(class_=AsyncSession),
        ),
        embeddings=lambda: index,
        overrides=KnowledgeOverrides(uow_factory=fake_uow_factory(store)),
    )
    return KnowledgeHarness(services, index, gateway, make_actor(Role.ADMIN), store)


@pytest.fixture(params=["fake", "sql"])
def h(
    request: pytest.FixtureRequest,
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
) -> KnowledgeHarness:
    """The same module on fakes and on PostgreSQL (the test transaction)."""
    if request.param == "fake":
        return request.getfixturevalue("fake_h")  # type: ignore[no-any-return]
    sessionmaker: async_sessionmaker[AsyncSession] = request.getfixturevalue(
        "sessionmaker_in_tx"
    )
    index, gateway = make_index(sessionmaker)
    services = build(
        _deps(settings, clock, redis, i18n, kicker, sessionmaker),
        embeddings=lambda: index,
        overrides=KnowledgeOverrides(
            uow_factory=lambda: SqlKnowledgeUnitOfWork(
                sessionmaker, noop_outbox_writer, noop_audit_writer
            )
        ),
    )
    return KnowledgeHarness(services, index, gateway, make_actor(Role.ADMIN))
