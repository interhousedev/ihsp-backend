"""The wiring function builds the module from ModuleDeps (GEN-8 composition root)."""

from collections.abc import AsyncIterator

from app.modules.files.wiring import build
from app.settings import Settings
from app.shared.contracts.files import FilesApi
from app.shared.db.engine import make_engine, make_sessionmaker
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.fakes.clock import FixedClock
from tests.fakes.files.sniffer import SignatureSniffer
from tests.fakes.tasks import FakeTaskKicker

import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def lazy_sessionmaker(
    settings: Settings,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A sessionmaker on an engine that never connects in these tests."""
    engine = make_engine(settings.database.url, pool_size=1)
    yield make_sessionmaker(engine)
    await engine.dispose()


def _deps(
    settings: Settings,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    redis: FakeRedis,
    i18n: I18nCore,
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


async def test_build_reads_limits_from_settings_and_exposes_the_files_api(
    settings: Settings,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    redis: FakeRedis,
    i18n: I18nCore,
    lazy_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """``container.files.public`` implements the FilesApi protocol."""
    deps = _deps(settings, clock, kicker, redis, i18n, lazy_sessionmaker)

    services = build(deps, sniffer=SignatureSniffer())

    public: FilesApi = services.public
    assert services.limits.student_quota_bytes == settings.limits.storage_student_bytes
    assert services.limits.staff_quota_bytes == settings.limits.storage_staff_bytes
    assert services.limits.file_max_bytes == settings.limits.file_max_bytes
    assert services.limits.ai_text_max_bytes == settings.limits.ai_text_max_bytes
    assert services.limits.library_file_max_bytes == settings.library.file_max_bytes
    assert (
        services.limits.library_student_quota_bytes
        == settings.library.student_quota_bytes
    )
    assert (
        services.limits.library_teacher_quota_bytes
        == settings.library.teacher_quota_bytes
    )
    for method in (
        "get",
        "get_many",
        "download_url",
        "read_bytes",
        "read_text_page",
        "search_text",
        "store_bytes",
        "check_access",
        "list_owned",
        "read_outline",
        "page_count",
        "sha256",
        "combine_images_to_pdf",
        "delete_file",
    ):
        assert callable(getattr(public, method))
    await services.close()


async def test_build_creates_the_s3_client_lazily_and_close_is_safe(
    settings: Settings,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    redis: FakeRedis,
    i18n: I18nCore,
    lazy_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Building opens no connection; close() may be called twice."""
    deps = _deps(settings, clock, kicker, redis, i18n, lazy_sessionmaker)

    services = build(deps, sniffer=SignatureSniffer())

    assert len(services.closers) == 1
    await services.close()
    await services.close()
