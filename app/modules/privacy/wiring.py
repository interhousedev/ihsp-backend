"""Builds the privacy module (container.privacy)."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.files.ports.storage import ObjectStorage
from app.modules.privacy.application.erase_owner import EraseOwner
from app.modules.privacy.application.erasure import (
    ApproveErasure,
    CancelErasure,
    ErasureLifecycle,
    GetMyErasure,
    ListErasureRequests,
    RejectErasure,
)
from app.modules.privacy.application.exports import (
    BuildExport,
    CleanupExports,
    DownloadExport,
    ListExports,
    RequestExport,
)
from app.modules.privacy.infrastructure.owned_files import SqlOwnedFiles
from app.modules.privacy.infrastructure.uow import SqlPrivacyUnitOfWork
from app.modules.privacy.ports.gateways import OwnedFiles
from app.modules.privacy.ports.unit_of_work import UowFactory
from app.shared.contracts.privacy import AccountControl
from app.shared.personal_data import PersonalData
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class PrivacyServices:
    """Use cases of the privacy module."""

    erasure: ErasureLifecycle  # the ErasureGateway identity calls
    get_my_erasure: GetMyErasure
    cancel_erasure: CancelErasure
    list_erasure_requests: ListErasureRequests
    approve_erasure: ApproveErasure
    reject_erasure: RejectErasure
    request_export: RequestExport
    list_exports: ListExports
    download_export: DownloadExport
    build_export: BuildExport
    cleanup_exports: CleanupExports
    erase_owner: EraseOwner


def build(
    deps: ModuleDeps,
    *,
    accounts: AccountControl,
    storage: ObjectStorage,
    export_sources: Sequence[PersonalData],
    erase_sources: Sequence[PersonalData],
    owned_files: OwnedFiles | None = None,
    uow_factory: UowFactory | None = None,
) -> PrivacyServices:
    """Wire the module; the factory and the files source are replaced in tests.

    ``export_sources`` describe every module's tables; ``erase_sources`` leave out
    the tables that ``<module>.delete_owner`` tasks erase together with their objects.
    """
    factory = uow_factory or _sql_uow_factory(deps)
    erasure = ErasureLifecycle(uow_factory=factory, clock=deps.clock)
    return PrivacyServices(
        erasure=erasure,
        get_my_erasure=GetMyErasure(uow_factory=factory),
        cancel_erasure=CancelErasure(uow_factory=factory, clock=deps.clock),
        list_erasure_requests=ListErasureRequests(
            uow_factory=factory, accounts=accounts
        ),
        approve_erasure=ApproveErasure(
            uow_factory=factory, accounts=accounts, clock=deps.clock
        ),
        reject_erasure=RejectErasure(
            uow_factory=factory, accounts=accounts, clock=deps.clock
        ),
        request_export=RequestExport(
            uow_factory=factory, kicker=deps.kicker, clock=deps.clock
        ),
        list_exports=ListExports(uow_factory=factory),
        download_export=DownloadExport(
            uow_factory=factory, storage=storage, clock=deps.clock
        ),
        build_export=BuildExport(
            uow_factory=factory,
            sources=export_sources,
            files=owned_files or SqlOwnedFiles(deps.sessionmaker),
            storage=storage,
            accounts=accounts,
            clock=deps.clock,
        ),
        cleanup_exports=CleanupExports(
            uow_factory=factory, storage=storage, clock=deps.clock
        ),
        erase_owner=EraseOwner(
            uow_factory=factory,
            sources=erase_sources,
            storage=storage,
            erasure=erasure,
        ),
    )


def _sql_uow_factory(deps: ModuleDeps) -> UowFactory:
    def make() -> SqlPrivacyUnitOfWork:
        return SqlPrivacyUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return make
