"""Fixtures of the LMS learning tests: services over the real database and fakes."""

from collections.abc import Callable

from app.modules.lms.wiring_learning import LearningServices, build_learning
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker
from tests.lms.learning.fakes.identity import FakeIdentityDirectory
from tests.lms.learning.fakes.preview_revisions import FakePreviewRevisions

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def identity() -> FakeIdentityDirectory:
    """Users known to the fake identity directory."""
    return FakeIdentityDirectory()


@pytest.fixture
def previews() -> FakePreviewRevisions:
    """The fake authoring port that freezes preview revisions."""
    return FakePreviewRevisions()


@pytest.fixture
def maker(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> async_sessionmaker[AsyncSession]:
    """Sessions on the test transaction (used by builders and the use cases)."""
    return sessionmaker_in_tx


@pytest.fixture
def deps(
    settings: Settings,
    i18n: I18nCore,
    clock: FixedClock,
    redis: FakeRedis,
    maker: async_sessionmaker[AsyncSession],
    kicker: FakeTaskKicker,
) -> ModuleDeps:
    """Module infrastructure with no-op outbox and audit writers."""
    return ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=maker,
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=noop_outbox_writer,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )


@pytest.fixture
def learning(
    deps: ModuleDeps,
    identity: FakeIdentityDirectory,
    previews: FakePreviewRevisions,
) -> LearningServices:
    """The learning use cases wired as in production, with fakes at the edges."""
    return build_learning(deps, identity=identity, preview_revisions=previews)


@pytest.fixture
def student(identity: FakeIdentityDirectory, make_actor: Callable[..., Actor]) -> Actor:
    """A student known to the identity directory."""
    user = identity.add(first_name="Sam", last_name="Student")
    return make_actor(Role.STUDENT, user_id=user.id)


@pytest.fixture
def other_student(
    identity: FakeIdentityDirectory, make_actor: Callable[..., Actor]
) -> Actor:
    """A second student."""
    user = identity.add(first_name="Olga", last_name="Other")
    return make_actor(Role.STUDENT, user_id=user.id)


@pytest.fixture
def teacher(identity: FakeIdentityDirectory, make_actor: Callable[..., Actor]) -> Actor:
    """A teacher (course staff when a test adds the staff row)."""
    user = identity.add(first_name="Tim", last_name="Teacher")
    return make_actor(Role.TEACHER, user_id=user.id)


@pytest.fixture
def lms_admin(
    identity: FakeIdentityDirectory, make_actor: Callable[..., Actor]
) -> Actor:
    """An LMS administrator."""
    user = identity.add(first_name="Ann", last_name="Admin")
    return make_actor(Role.LMS_ADMIN, user_id=user.id)
