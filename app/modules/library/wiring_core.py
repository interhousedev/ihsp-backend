"""Services every area of the library builds on (the shared half of the module)."""

from collections.abc import Callable
from dataclasses import dataclass

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.detail import DetailBuilder
from app.modules.library.infrastructure.redis_stats import RedisStatsRecorder
from app.modules.library.infrastructure.subject_directory import (
    LibrarySubjectDirectory,
)
from app.modules.library.infrastructure.uow import LibrarySqlUnitOfWork
from app.modules.library.ports.directories import AcademicDirectory
from app.modules.library.ports.stats_recorder import StatsRecorder
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.settings import LibrarySettings
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker
from app.shared.wiring import ModuleDeps


@dataclass(frozen=True, slots=True)
class CoreOverrides:
    """Replacements tests pass in."""

    uow_factory: UowFactory | None = None
    stats: StatsRecorder | None = None


@dataclass(frozen=True, slots=True)
class LibraryCore:
    """Dependencies and shared services handed to every area's `build_*`."""

    deps: ModuleDeps
    settings: LibrarySettings
    clock: Clock
    kicker: TaskKicker
    rate_limiter: RateLimiter
    i18n: I18nCore
    uow_factory: UowFactory
    identity: IdentityDirectory
    files: FilesApi
    academic: AcademicDirectory
    cards: CardBuilder
    detail: DetailBuilder
    stats: StatsRecorder


def make_uow_factory(deps: ModuleDeps) -> Callable[[], LibraryUnitOfWork]:
    """A factory of SQL units of work over the module's sessionmaker."""

    def factory() -> LibraryUnitOfWork:
        return LibrarySqlUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return factory


def build_core(
    deps: ModuleDeps,
    *,
    identity: IdentityDirectory,
    files: FilesApi,
    academic: AcademicDirectory,
    overrides: CoreOverrides | None = None,
) -> LibraryCore:
    """Assemble the shared services."""
    given = overrides or CoreOverrides()
    uow_factory = given.uow_factory or make_uow_factory(deps)
    academic = LibrarySubjectDirectory(academic, uow_factory)
    settings = deps.settings.library
    cards = CardBuilder(
        academic=academic, files=files, cover_ttl_seconds=settings.reader_url_seconds
    )
    return LibraryCore(
        deps=deps,
        settings=settings,
        clock=deps.clock,
        kicker=deps.kicker,
        rate_limiter=deps.rate_limiter,
        i18n=deps.i18n,
        uow_factory=uow_factory,
        identity=identity,
        files=files,
        academic=academic,
        cards=cards,
        detail=DetailBuilder(cards=cards, i18n=deps.i18n, academic=academic),
        stats=given.stats or RedisStatsRecorder(deps.redis, deps.clock),
    )
