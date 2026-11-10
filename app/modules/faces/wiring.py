"""Builds the faces module (container.faces)."""

from dataclasses import dataclass
from pathlib import Path

from app.modules.faces.application.devices import (
    CreateDevice,
    ListDeviceCalls,
    ListDevices,
    PurgeOld,
    RevokeDevice,
)
from app.modules.faces.application.enroll import FaceEnroller
from app.modules.faces.application.face_queries import (
    DeleteMyFace,
    GetMyFace,
    GetUserFacePhoto,
    UploadMyFace,
)
from app.modules.faces.application.identify_face import (
    AuthenticateDevice,
    IdentifyFace,
)
from app.modules.faces.application.staff_face import (
    StaffDeleteFace,
    StaffFaceGuard,
    StaffUploadFace,
)
from app.modules.faces.infrastructure.engines.fake import FakeFaceEngine
from app.modules.faces.infrastructure.engines.opencv import OpenCvFaceEngine
from app.modules.faces.infrastructure.uow import SqlFacesUnitOfWork
from app.modules.faces.ports.directory import StudentDirectory
from app.modules.faces.ports.engine import FaceEngine, ImageSniffer
from app.modules.faces.ports.unit_of_work import UowFactory
from app.shared.contracts.excuses import ExcuseStatusReader
from app.shared.contracts.files import FilesApi
from app.shared.wiring import ModuleDeps


@dataclass(slots=True)
class FacesServices:
    """Use cases of the faces module."""

    get_my_face: GetMyFace
    upload_my_face: UploadMyFace
    delete_my_face: DeleteMyFace
    admin_get_face: GetUserFacePhoto
    staff_upload: StaffUploadFace
    staff_delete: StaffDeleteFace
    create_device: CreateDevice
    list_devices: ListDevices
    revoke_device: RevokeDevice
    list_calls: ListDeviceCalls
    identify: IdentifyFace
    purge_old: PurgeOld


@dataclass(frozen=True, slots=True)
class FacesOverrides:
    """Replacements for the engine and the unit of work (for tests)."""

    uow_factory: UowFactory | None = None
    engine: FaceEngine | None = None


def build(
    deps: ModuleDeps,
    *,
    files: FilesApi,
    directory: StudentDirectory,
    excuses: ExcuseStatusReader,
    sniffer: ImageSniffer,
    overrides: FacesOverrides | None = None,
) -> FacesServices:
    """Wire the module."""
    over = overrides or FacesOverrides()
    settings = deps.settings.faces
    uow_factory = over.uow_factory or _sql_uow_factory(deps)
    engine = over.engine or _engine(deps)
    enroller = FaceEnroller(
        uow_factory=uow_factory,
        engine=engine,
        sniffer=sniffer,
        files=files,
        clock=deps.clock,
    )
    reader = GetMyFace(uow_factory=uow_factory, files=files)
    guard = StaffFaceGuard(directory=directory)
    auth = AuthenticateDevice(uow_factory=uow_factory, clock=deps.clock)
    return FacesServices(
        get_my_face=reader,
        upload_my_face=UploadMyFace(enroller=enroller, reader=reader),
        delete_my_face=DeleteMyFace(enroller=enroller),
        admin_get_face=GetUserFacePhoto(uow_factory=uow_factory, files=files),
        staff_upload=StaffUploadFace(guard=guard, enroller=enroller, reader=reader),
        staff_delete=StaffDeleteFace(guard=guard, enroller=enroller),
        create_device=CreateDevice(uow_factory=uow_factory, clock=deps.clock),
        list_devices=ListDevices(uow_factory=uow_factory),
        revoke_device=RevokeDevice(uow_factory=uow_factory, clock=deps.clock),
        list_calls=ListDeviceCalls(
            uow_factory=uow_factory, directory=directory, clock=deps.clock
        ),
        identify=IdentifyFace(
            uow_factory=uow_factory,
            auth=auth,
            engine=engine,
            sniffer=sniffer,
            directory=directory,
            excuses=excuses,
            rate_limiter=deps.rate_limiter,
            clock=deps.clock,
            threshold=settings.match_threshold,
            per_minute=settings.device_rate_per_minute,
        ),
        purge_old=PurgeOld(uow_factory=uow_factory, clock=deps.clock),
    )


def _engine(deps: ModuleDeps) -> FaceEngine:
    settings = deps.settings.faces
    if settings.mode == "opencv":
        return OpenCvFaceEngine(Path(settings.model_dir))
    return FakeFaceEngine()


def _sql_uow_factory(deps: ModuleDeps) -> UowFactory:
    def make() -> SqlFacesUnitOfWork:
        return SqlFacesUnitOfWork(
            deps.sessionmaker,
            deps.outbox_writer,
            deps.audit_writer,
            deps.outbox_committed_hook,
        )

    return make
