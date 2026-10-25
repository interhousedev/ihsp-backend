"""Fixtures of the notebooks tests: SQL unit of work on the test transaction, actors."""

import dataclasses
from collections.abc import Callable
from typing import cast

from app.modules.notebooks.infrastructure.uow import SqlNotebooksUnitOfWork
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.modules.notebooks.wiring_core import CoreOverrides, NotebooksCore, build_core
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import IdentityDirectory
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.ai.contracts import FakeIdentity, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notebooks.llm import ScriptedLlm
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def uow_factory(sessionmaker_in_tx: async_sessionmaker[AsyncSession]) -> UowFactory:
    """A factory of SQL units of work on a savepoint of the test transaction."""

    def factory() -> NotebooksUnitOfWork:
        return SqlNotebooksUnitOfWork(
            sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer
        )

    return factory


@pytest.fixture
def student(make_actor: Callable[..., Actor]) -> Actor:
    """A student."""
    return make_actor(Role.STUDENT)


@pytest.fixture
def other_student(make_actor: Callable[..., Actor]) -> Actor:
    """Another student (owner of the notebooks that `student` must not see)."""
    return make_actor(Role.STUDENT)


@pytest.fixture
def identity(student: Actor, other_student: Actor) -> FakeIdentity:
    """Users for the two students (locale `en`)."""
    users = [
        dataclasses.replace(make_user(Role.STUDENT), id=actor.user_id)
        for actor in (student, other_student)
    ]
    return FakeIdentity(*users)


@pytest.fixture
def scripted_llm() -> ScriptedLlm:
    """The language model: scripted answers, the deterministic fake otherwise."""
    return ScriptedLlm()


@pytest.fixture
def module_deps(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> ModuleDeps:
    """Module infrastructure over the test transaction, fake Redis and clock."""
    return ModuleDeps(
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


@pytest.fixture
def core(
    module_deps: ModuleDeps,
    scripted_llm: ScriptedLlm,
    identity: FakeIdentity,
    uow_factory: UowFactory,
) -> NotebooksCore:
    """The shared services of the module over the test fakes."""
    return build_core(
        module_deps,
        gateway=scripted_llm,
        identity=cast(IdentityDirectory, identity),  # the locale lookup only
        overrides=CoreOverrides(uow_factory=uow_factory),
    )
