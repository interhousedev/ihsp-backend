"""FILE-5: parallel uploads cannot exceed the quota (real PostgreSQL)."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import UUID, uuid4

from app.modules.files.domain.errors import QuotaExceededError
from app.modules.files.infrastructure.extraction.extractor import FileTextExtractor
from app.modules.files.infrastructure.orm.file import File
from app.modules.files.infrastructure.uow import SqlFilesUnitOfWork
from app.modules.files.wiring import FilesServices, assemble
from app.shared.actor import Actor, Role
from app.shared.contracts.files import FilePurpose
from app.shared.db.engine import make_sessionmaker
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from tests.fakes.clock import FixedClock
from tests.fakes.files.resolvers import FakeTermResolver, FakeUsageResolver
from tests.fakes.files.services import DEFAULT_LIMITS
from tests.fakes.files.sniffer import SignatureSniffer
from tests.fakes.files.storage import InMemoryStorage
from tests.fakes.tasks import FakeTaskKicker
from tests.files.helpers import sha256_b64

import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

DATA = b"%PDF-1.4 six"  # 12 bytes
QUOTA = 20  # room for exactly one 12-byte file


class SlowReadUow(SqlFilesUnitOfWork):
    """Pauses between reading the used bytes and inserting, to widen the race."""

    def _init_repos(self) -> None:
        super()._init_repos()
        repo = self.files
        read = repo.used_bytes

        async def slow_used_bytes(*args: object, **kwargs: object) -> int:
            used: int = await read(*args, **kwargs)  # type: ignore[arg-type]
            await asyncio.sleep(0.3)
            return used

        repo.used_bytes = slow_used_bytes  # type: ignore[method-assign]


@pytest_asyncio.fixture
async def services(
    engine: AsyncEngine, clock: FixedClock, kicker: FakeTaskKicker
) -> AsyncIterator[FilesServices]:
    """The module over committed transactions on separate connections."""
    sessionmaker = make_sessionmaker(engine)

    def uow_factory() -> SlowReadUow:
        return SlowReadUow(sessionmaker, noop_outbox_writer, noop_audit_writer)

    limits = replace(DEFAULT_LIMITS, student_quota_bytes=QUOTA)
    yield assemble(
        uow_factory=uow_factory,
        clock=clock,
        kicker=kicker,
        storage=InMemoryStorage(),
        terms=FakeTermResolver(),
        usage=FakeUsageResolver(),
        sniffer=SignatureSniffer(),
        extractor=FileTextExtractor(),
        limits=limits,
        closers=[],
    )


async def _row_count(engine: AsyncEngine, owner: UUID) -> int:
    async with engine.connect() as connection:
        result = await connection.execute(
            select(func.count()).select_from(File).where(File.owner_id == owner)
        )
        return int(result.scalar_one())


async def _forget(engine: AsyncEngine, owner: UUID) -> None:
    async with engine.begin() as connection:
        await connection.execute(delete(File).where(File.owner_id == owner))


async def test_parallel_requests_cannot_both_fit_into_the_quota(
    engine: AsyncEngine, services: FilesServices
) -> None:
    """Two coroutines on two connections: exactly one reservation succeeds."""
    student = Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))

    async def ask() -> object:
        return await services.request_upload.execute(
            student,
            name="a.pdf",
            size=len(DATA),
            content_type="application/pdf",
            sha256_b64=sha256_b64(DATA),
            purpose=FilePurpose.LINK,
        )

    try:
        results = await asyncio.gather(ask(), ask(), return_exceptions=True)

        failures = [r for r in results if isinstance(r, QuotaExceededError)]
        assert len(failures) == 1
        assert sum(1 for r in results if not isinstance(r, BaseException)) == 1
        assert await _row_count(engine, student.user_id) == 1
    finally:
        await _forget(engine, student.user_id)


async def test_many_parallel_requests_reserve_at_most_the_quota(
    engine: AsyncEngine, services: FilesServices
) -> None:
    """Five at once: the sum of accepted sizes never exceeds the quota."""
    student = Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))

    async def ask() -> object:
        return await services.request_upload.execute(
            student,
            name="a.pdf",
            size=len(DATA),
            content_type="application/pdf",
            sha256_b64=sha256_b64(DATA),
            purpose=FilePurpose.LINK,
        )

    try:
        results = await asyncio.gather(
            *(ask() for _ in range(5)), return_exceptions=True
        )

        accepted = [r for r in results if not isinstance(r, BaseException)]
        assert len(accepted) * len(DATA) <= QUOTA
        assert len(accepted) == 1
        assert all(
            isinstance(r, QuotaExceededError)
            for r in results
            if isinstance(r, BaseException)
        )
    finally:
        await _forget(engine, student.user_id)


async def test_the_lock_is_per_owner_so_other_users_do_not_wait(
    engine: AsyncEngine, services: FilesServices
) -> None:
    """Two different students upload in parallel and both succeed."""
    first = Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))
    second = Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))

    async def ask(actor: Actor) -> object:
        return await services.request_upload.execute(
            actor,
            name="a.pdf",
            size=len(DATA),
            content_type="application/pdf",
            sha256_b64=sha256_b64(DATA),
            purpose=FilePurpose.LINK,
        )

    try:
        results = await asyncio.gather(ask(first), ask(second))

        assert len(results) == 2
        assert await _row_count(engine, first.user_id) == 1
        assert await _row_count(engine, second.user_id) == 1
    finally:
        await _forget(engine, first.user_id)
        await _forget(engine, second.user_id)
