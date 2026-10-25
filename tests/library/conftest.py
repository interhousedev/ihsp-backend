"""Fixtures of the library tests: SQL unit of work on the test transaction, actors."""

from collections.abc import Awaitable, Callable
from typing import cast

from app.modules.library.domain.entities import Item
from app.modules.library.infrastructure.uow import LibrarySqlUnitOfWork
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.modules.library.wiring import LibraryServices, build
from app.modules.library.wiring_core import CoreOverrides
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.library.academic import FakeAcademicDirectory
from tests.fakes.library.files import FakeFilesApi
from tests.fakes.library.identity import FakeLibraryIdentity
from tests.fakes.tasks import FakeTaskKicker

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def uow_factory(sessionmaker_in_tx: async_sessionmaker[AsyncSession]) -> UowFactory:
    """A factory of SQL units of work on a savepoint of the test transaction."""

    def factory() -> LibraryUnitOfWork:
        return LibrarySqlUnitOfWork(
            sessionmaker_in_tx, noop_outbox_writer, noop_audit_writer
        )

    return factory


@pytest.fixture
def student(make_actor: Callable[..., Actor]) -> Actor:
    """A student."""
    return make_actor(Role.STUDENT)


@pytest.fixture
def other_student(make_actor: Callable[..., Actor]) -> Actor:
    """Another student."""
    return make_actor(Role.STUDENT)


@pytest.fixture
def teacher(make_actor: Callable[..., Actor]) -> Actor:
    """A teacher."""
    return make_actor(Role.TEACHER)


@pytest.fixture
def librarian(make_actor: Callable[..., Actor]) -> Actor:
    """A student who is also a librarian."""
    return make_actor(Role.STUDENT, Role.LIBRARIAN)


@pytest.fixture
def other_librarian(make_actor: Callable[..., Actor]) -> Actor:
    """Another librarian."""
    return make_actor(Role.LIBRARIAN)


@pytest.fixture
def admin(make_actor: Callable[..., Actor]) -> Actor:
    """Administration."""
    return make_actor(Role.ADMIN)


@pytest.fixture
def identity(
    student: Actor,
    other_student: Actor,
    teacher: Actor,
    librarian: Actor,
    other_librarian: Actor,
    admin: Actor,
) -> FakeLibraryIdentity:
    """Users for every actor (names Aziza Karimova, Bobur Aliyev, ...)."""
    directory = FakeLibraryIdentity()
    directory.add(student, first="Aziza", last="Karimova")
    directory.add(other_student, first="Bobur", last="Aliyev")
    directory.add(teacher, first="Dilnoza", last="Rahimova")
    directory.add(librarian, first="Sardor", last="Tursunov")
    directory.add(other_librarian, first="Malika", last="Yusupova")
    directory.add(admin, first="Admin", last="Adminov")
    return directory


@pytest.fixture
def files_api() -> FakeFilesApi:
    """In-memory files."""
    return FakeFilesApi()


@pytest.fixture
def academic(student: Actor) -> FakeAcademicDirectory:
    """Subjects and groups; the student has cohort 2025."""
    directory = FakeAcademicDirectory()
    directory.cohorts[student.user_id] = "2025"
    return directory


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
def library(
    module_deps: ModuleDeps,
    identity: FakeLibraryIdentity,
    files_api: FakeFilesApi,
    academic: FakeAcademicDirectory,
    uow_factory: UowFactory,
) -> LibraryServices:
    """The whole module over the test fakes."""
    return build(
        module_deps,
        identity=cast(IdentityDirectory, identity),
        files=cast(FilesApi, files_api),
        academic=academic,
        overrides=CoreOverrides(uow_factory=uow_factory),
    )


@pytest_asyncio.fixture
async def store_item(
    uow_factory: UowFactory,
) -> Callable[[Item], Awaitable[Item]]:
    """Persist an item built by a factory and return it."""

    async def store(item: Item) -> Item:
        async with uow_factory() as uow:
            await uow.items.add(item)
            await uow.commit()
        return item

    return store
