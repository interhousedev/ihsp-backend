"""Fixtures of the faces tests: the module on in-memory fakes."""

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.faces.infrastructure.engines.fake import FakeFaceEngine
from app.modules.faces.wiring import FacesOverrides, FacesServices, build
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.faces.uow import (
    FakeDirectory,
    FakeExcuses,
    FakeFaceFiles,
    FakeFacesStore,
    FakeFacesUow,
    FakeSniffer,
)
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PNG = b"\x89PNG\r\n\x1a\n"


def photo(tag: str) -> bytes:
    """A small PNG-looking file; the fake engine derives the face from the bytes."""
    return PNG + tag.encode()


@dataclass
class FacesHarness:
    """The wired module and the fakes behind it."""

    services: FacesServices
    store: FakeFacesStore
    directory: FakeDirectory
    excuses: FakeExcuses
    files: FakeFaceFiles
    clock: FixedClock
    admin: Actor
    curator: Actor


@pytest.fixture
def fh(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    make_actor: Callable[..., Actor],
) -> FacesHarness:
    """The module on fakes, with an admin and a curator."""
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
    store = FakeFacesStore()
    directory = FakeDirectory()
    excuses = FakeExcuses()
    files = FakeFaceFiles()
    services = build(
        deps,
        files=files,  # type: ignore[arg-type]
        directory=directory,
        excuses=excuses,
        sniffer=FakeSniffer(),
        overrides=FacesOverrides(
            uow_factory=lambda: FakeFacesUow(store), engine=FakeFaceEngine()
        ),
    )
    return FacesHarness(
        services, store, directory, excuses, files, clock,
        make_actor(Role.ADMIN), make_actor(Role.TEACHER),
    )  # fmt: skip
