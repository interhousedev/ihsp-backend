"""Builds the files module: use cases, jobs and the public FilesApi."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.modules.files.application.cleanup_expired import CleanupExpired
from app.modules.files.application.complete_upload import CompleteUpload
from app.modules.files.application.delete_file import DeleteFile
from app.modules.files.application.delete_owner_files import DeleteOwnerFiles
from app.modules.files.application.download_links import DownloadLinks
from app.modules.files.application.file_views import FileViewBuilder
from app.modules.files.application.get_download_url import GetDownloadUrl
from app.modules.files.application.get_file import GetFile
from app.modules.files.application.list_my_files import ListMyFiles
from app.modules.files.application.list_owned_files import ListOwnedFiles
from app.modules.files.application.process_file import ProcessFile
from app.modules.files.application.public_api import FilesApiImpl
from app.modules.files.application.purge_pending import PurgePending
from app.modules.files.application.read_file_bytes import ReadFileBytes
from app.modules.files.application.read_text_page import ReadTextPage
from app.modules.files.application.rename_file import RenameFile
from app.modules.files.application.request_upload import RequestUpload
from app.modules.files.application.search_text import SearchText
from app.modules.files.application.storage_usage import StorageUsage
from app.modules.files.application.store_bytes import StoreBytes
from app.modules.files.application.sweep_processing import SweepProcessing
from app.modules.files.application.warn_expiring import WarnExpiring
from app.modules.files.domain.policy import FilesLimits
from app.modules.files.infrastructure.extraction.extractor import FileTextExtractor
from app.modules.files.infrastructure.null_resolvers import (
    NoTermResolver,
    NoUsageResolver,
)
from app.modules.files.infrastructure.s3.storage import S3Storage
from app.modules.files.infrastructure.sniffing.magic_sniffer import MagicSniffer
from app.modules.files.infrastructure.uow import SqlFilesUnitOfWork
from app.modules.files.ports.content_sniffer import ContentSniffer
from app.modules.files.ports.storage import ObjectStorage
from app.modules.files.ports.term_resolver import TermResolver
from app.modules.files.ports.text_extractor import TextExtractor
from app.modules.files.ports.unit_of_work import UowFactory
from app.modules.files.ports.usage_resolver import UsageResolver
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class FilesServices:
    """Use cases of the files module (attribute = use case file name) and the API."""

    request_upload: RequestUpload
    complete_upload: CompleteUpload
    process_file: ProcessFile
    get_file: GetFile
    get_download_url: GetDownloadUrl
    rename_file: RenameFile
    delete_file: DeleteFile
    list_my_files: ListMyFiles
    list_owned_files: ListOwnedFiles
    storage_usage: StorageUsage
    store_bytes: StoreBytes
    read_text_page: ReadTextPage
    read_file_bytes: ReadFileBytes
    search_text: SearchText
    cleanup_expired: CleanupExpired
    warn_expiring: WarnExpiring
    purge_pending: PurgePending
    sweep_processing: SweepProcessing
    delete_owner_files: DeleteOwnerFiles
    public: FilesApiImpl
    limits: FilesLimits
    closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list)

    async def close(self) -> None:
        """Close the storage client (call at shutdown)."""
        for closer in self.closers:
            await closer()


def build(
    deps: ModuleDeps,
    *,
    terms: TermResolver | None = None,
    usage: UsageResolver | None = None,
    storage: ObjectStorage | None = None,
    sniffer: ContentSniffer | None = None,
    extractor: TextExtractor | None = None,
) -> FilesServices:
    """Build the module; ``terms`` and ``usage`` are connected by I1.

    Without them students' files belong to no term and 'used by' lists are empty.
    """
    settings = deps.settings
    closers: list[Callable[[], Awaitable[None]]] = []
    if storage is None:
        s3 = S3Storage(
            endpoint_url=settings.s3.endpoint_url,
            public_endpoint_url=settings.s3.public_endpoint_url,
            region=settings.s3.region,
            access_key=settings.s3.access_key,
            secret_key=settings.s3.secret_key.get_secret_value(),
            bucket=settings.s3.bucket,
        )
        closers.append(s3.close)
        storage = s3
    limits = FilesLimits(
        student_quota_bytes=settings.limits.storage_student_bytes,
        staff_quota_bytes=settings.limits.storage_staff_bytes,
        file_max_bytes=settings.limits.file_max_bytes,
        ai_text_max_bytes=settings.limits.ai_text_max_bytes,
    )

    def uow_factory() -> SqlFilesUnitOfWork:
        return SqlFilesUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return assemble(
        uow_factory=uow_factory,
        clock=deps.clock,
        kicker=deps.kicker,
        storage=storage,
        terms=terms or NoTermResolver(),
        usage=usage or NoUsageResolver(),
        sniffer=sniffer or MagicSniffer(),
        extractor=extractor or FileTextExtractor(),
        limits=limits,
        closers=closers,
    )


def assemble(
    *,
    uow_factory: UowFactory,
    clock: Clock,
    kicker: TaskKicker,
    storage: ObjectStorage,
    terms: TermResolver,
    usage: UsageResolver,
    sniffer: ContentSniffer,
    extractor: TextExtractor,
    limits: FilesLimits,
    closers: list[Callable[[], Awaitable[None]]],
) -> FilesServices:
    """Create the use cases from ready-made adapters (tests pass fakes)."""
    views = FileViewBuilder(terms, usage, limits)
    links = DownloadLinks(storage, clock)
    read_bytes = ReadFileBytes(uow_factory=uow_factory, storage=storage)
    read_page = ReadTextPage(uow_factory=uow_factory, storage=storage)
    search = SearchText(uow_factory=uow_factory, storage=storage)
    list_owned = ListOwnedFiles(uow_factory=uow_factory)
    store = StoreBytes(
        uow_factory=uow_factory,
        storage=storage,
        sniffer=sniffer,
        terms=terms,
        clock=clock,
        kicker=kicker,
        limits=limits,
    )
    return FilesServices(
        request_upload=RequestUpload(
            uow_factory=uow_factory,
            storage=storage,
            terms=terms,
            views=views,
            clock=clock,
            limits=limits,
        ),
        complete_upload=CompleteUpload(
            uow_factory=uow_factory,
            storage=storage,
            sniffer=sniffer,
            views=views,
            clock=clock,
            kicker=kicker,
        ),
        process_file=ProcessFile(
            uow_factory=uow_factory, storage=storage, extractor=extractor, clock=clock
        ),
        get_file=GetFile(uow_factory=uow_factory, views=views),
        get_download_url=GetDownloadUrl(uow_factory=uow_factory, links=links),
        rename_file=RenameFile(uow_factory=uow_factory, views=views, clock=clock),
        delete_file=DeleteFile(
            uow_factory=uow_factory, storage=storage, usage=usage, clock=clock
        ),
        list_my_files=ListMyFiles(uow_factory=uow_factory, views=views),
        list_owned_files=list_owned,
        storage_usage=StorageUsage(
            uow_factory=uow_factory, terms=terms, clock=clock, limits=limits
        ),
        store_bytes=store,
        read_text_page=read_page,
        read_file_bytes=read_bytes,
        search_text=search,
        cleanup_expired=CleanupExpired(
            uow_factory=uow_factory, storage=storage, terms=terms, clock=clock
        ),
        warn_expiring=WarnExpiring(uow_factory=uow_factory, terms=terms, clock=clock),
        purge_pending=PurgePending(
            uow_factory=uow_factory, storage=storage, clock=clock
        ),
        sweep_processing=SweepProcessing(
            uow_factory=uow_factory, kicker=kicker, clock=clock
        ),
        delete_owner_files=DeleteOwnerFiles(
            uow_factory=uow_factory, storage=storage, clock=clock
        ),
        public=FilesApiImpl(
            uow_factory=uow_factory,
            links=links,
            read_bytes_uc=read_bytes,
            read_text_page_uc=read_page,
            search_text_uc=search,
            store_bytes_uc=store,
            list_owned_uc=list_owned,
        ),
        limits=limits,
        closers=closers,
    )
