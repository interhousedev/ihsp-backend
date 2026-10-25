"""Wiring of Common Cartridge import and export (`container.lms.cartridge`)."""

from dataclasses import dataclass

from app.modules.lms.application.authoring.create_course import CreateCourse
from app.modules.lms.application.authoring.draft_writer import StepDraftWriter
from app.modules.lms.application.authoring.presenter import Presenter
from app.modules.lms.application.authoring.uow_factory import UowFactory
from app.modules.lms.application.cartridge.copy_course import CopyCourse
from app.modules.lms.application.cartridge.export_cartridge import ExportCartridge
from app.modules.lms.application.cartridge.import_cartridge import ImportCartridge
from app.modules.lms.application.cartridge.import_jobs import (
    GetCartridgeImport,
    RunCartridgeImport,
    StartCartridgeImport,
)
from app.modules.lms.infrastructure.authoring.uow import SqlAuthoringUnitOfWork
from app.modules.lms.infrastructure.cartridge_reports import (
    RedisCartridgeImportResults,
)
from app.modules.lms.ports.authoring.unit_of_work import AuthoringUnitOfWork
from app.modules.lms.ports.cartridge_reports import CartridgeImportResults
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.contracts.identity import IdentityDirectory
from app.shared.jobs import JobTracker, RedisJobTracker
from app.shared.tasks import TaskKicker
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class CartridgeServices:
    """Import (start, run in the worker, poll) and export."""

    start_import: StartCartridgeImport
    run_import: RunCartridgeImport
    get_import: GetCartridgeImport
    import_cartridge: ImportCartridge
    export: ExportCartridge
    copy: CopyCourse


def build_cartridge(
    deps: ModuleDeps, *, identity: IdentityDirectory, files: FilesApi
) -> CartridgeServices:
    """Build on SQL repositories and Redis."""

    def uow_factory() -> AuthoringUnitOfWork:
        return SqlAuthoringUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return assemble_cartridge(
        uow_factory,
        clock=deps.clock,
        identity=identity,
        files=files,
        kicker=deps.kicker,
        tracker=RedisJobTracker(deps.redis),
        results=RedisCartridgeImportResults(deps.redis),
    )


def assemble_cartridge(
    uow_factory: UowFactory,
    *,
    clock: Clock,
    identity: IdentityDirectory,
    files: FilesApi,
    kicker: TaskKicker,
    tracker: JobTracker,
    results: CartridgeImportResults,
) -> CartridgeServices:
    """Connect the use cases (SQL or fakes)."""
    importer = ImportCartridge(
        uow_factory,
        clock,
        files,
        StepDraftWriter(files),
        CreateCourse(uow_factory, clock, Presenter(identity)),
    )
    exporter = ExportCartridge(uow_factory, files)
    return CartridgeServices(
        start_import=StartCartridgeImport(files, kicker, tracker),
        run_import=RunCartridgeImport(files, tracker, results, importer),
        get_import=GetCartridgeImport(tracker, results),
        import_cartridge=importer,
        export=exporter,
        copy=CopyCourse(exporter, importer),
    )
