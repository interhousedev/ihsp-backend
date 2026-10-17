"""Builds the certificates module: use cases over a unit of work and ports."""

from dataclasses import dataclass

from app.modules.certificates.application.add_entry_file import AddEntryFile
from app.modules.certificates.application.create_entry import CreateEntry
from app.modules.certificates.application.create_type import CreateType
from app.modules.certificates.application.delete_entry import DeleteEntry
from app.modules.certificates.application.delete_type import DeleteType
from app.modules.certificates.application.export_entries import ExportEntries
from app.modules.certificates.application.get_file_download import GetFileDownload
from app.modules.certificates.application.get_staff_ranking import GetStaffRanking
from app.modules.certificates.application.get_staff_stats import GetStaffStats
from app.modules.certificates.application.import_emis import ImportEmis
from app.modules.certificates.application.list_my_entries import ListMyEntries
from app.modules.certificates.application.list_staff_entries import ListStaffEntries
from app.modules.certificates.application.list_staff_groups import ListStaffGroups
from app.modules.certificates.application.list_types import ListTypes
from app.modules.certificates.application.remove_entry_file import RemoveEntryFile
from app.modules.certificates.application.staff_scope import StaffScope
from app.modules.certificates.application.update_entry import UpdateEntry
from app.modules.certificates.application.update_type import UpdateType
from app.modules.certificates.infrastructure.fake_fetcher import FakeCertificateFetcher
from app.modules.certificates.infrastructure.safe_fetcher import SafeCertificateFetcher
from app.modules.certificates.infrastructure.uow import SqlCertificatesUnitOfWork
from app.modules.certificates.ports.fetcher import CertificateFetcher
from app.modules.certificates.ports.student_directory import StudentDirectory
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.contracts.emis import EmisSource
from app.shared.contracts.files import FilesApi
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class CertificatesServices:
    """Use cases of the certificates module (attribute name = use case file name)."""

    list_types: ListTypes
    create_type: CreateType
    update_type: UpdateType
    delete_type: DeleteType
    list_my_entries: ListMyEntries
    create_entry: CreateEntry
    update_entry: UpdateEntry
    delete_entry: DeleteEntry
    add_entry_file: AddEntryFile
    remove_entry_file: RemoveEntryFile
    get_file_download: GetFileDownload
    import_emis: ImportEmis
    list_staff_entries: ListStaffEntries
    get_staff_stats: GetStaffStats
    get_staff_ranking: GetStaffRanking
    list_staff_groups: ListStaffGroups
    export_entries: ExportEntries


@dataclass(frozen=True, slots=True)
class CertificatesOverrides:
    """Replacements for the SQL unit of work and the PDF fetcher (for tests)."""

    uow_factory: UowFactory | None = None
    fetcher: CertificateFetcher | None = None


def build(
    deps: ModuleDeps,
    *,
    files: FilesApi,
    emis: EmisSource,
    directory: StudentDirectory,
    overrides: CertificatesOverrides | None = None,
) -> CertificatesServices:
    """Wire the module."""
    over = overrides or CertificatesOverrides()
    uow_factory = over.uow_factory or _sql_uow_factory(deps)
    fetcher = over.fetcher or _make_fetcher(deps)
    scope = StaffScope(directory=directory)
    return CertificatesServices(
        list_types=ListTypes(uow_factory=uow_factory),
        create_type=CreateType(uow_factory=uow_factory),
        update_type=UpdateType(uow_factory=uow_factory),
        delete_type=DeleteType(uow_factory=uow_factory),
        list_my_entries=ListMyEntries(uow_factory=uow_factory),
        create_entry=CreateEntry(uow_factory=uow_factory, clock=deps.clock),
        update_entry=UpdateEntry(uow_factory=uow_factory),
        delete_entry=DeleteEntry(uow_factory=uow_factory, files=files),
        add_entry_file=AddEntryFile(uow_factory=uow_factory, files=files),
        remove_entry_file=RemoveEntryFile(uow_factory=uow_factory, files=files),
        get_file_download=GetFileDownload(
            uow_factory=uow_factory, files=files, directory=directory
        ),
        import_emis=ImportEmis(
            uow_factory=uow_factory,
            clock=deps.clock,
            emis=emis,
            files=files,
            fetcher=fetcher,
        ),
        list_staff_entries=ListStaffEntries(uow_factory=uow_factory, scope=scope),
        get_staff_stats=GetStaffStats(uow_factory=uow_factory, scope=scope),
        get_staff_ranking=GetStaffRanking(uow_factory=uow_factory, scope=scope),
        list_staff_groups=ListStaffGroups(scope=scope),
        export_entries=ExportEntries(uow_factory=uow_factory, scope=scope, files=files),
    )


def _make_fetcher(deps: ModuleDeps) -> CertificateFetcher:
    if deps.settings.emis.mode == "fake":
        return FakeCertificateFetcher()
    return SafeCertificateFetcher()


def _sql_uow_factory(deps: ModuleDeps) -> UowFactory:
    def make() -> SqlCertificatesUnitOfWork:
        return SqlCertificatesUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return make
