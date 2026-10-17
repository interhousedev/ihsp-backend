"""Routes: start an .imscc import, follow it, export a course as .imscc, copy."""

from typing import Annotated, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep
from app.modules.lms.domain.cartridge.archive import MAX_ARCHIVE_BYTES
from app.modules.lms.domain.cartridge.errors import CartridgeInvalidError

from fastapi import APIRouter, Depends, File, Response, UploadFile
from pydantic import BaseModel

ContainerDep = Annotated[Container, Depends(get_container)]
JobStatus = Literal["queued", "running", "stopping", "done", "failed", "cancelled"]


class CartridgeImportStarted(BaseModel):
    """The job that imports the cartridge."""

    job_id: str


class CartridgeReportItem(BaseModel):
    """An item kept only as a link or note, or skipped."""

    title: str
    kind: str
    note: str


class CartridgeImportReport(BaseModel):
    """What the import created and what it could not map."""

    title: str
    sections: int
    steps: int
    files: int
    quizzes: int
    questions: int
    links: int
    items: list[CartridgeReportItem]


class CartridgeImportStatus(BaseModel):
    """Progress of an import; ``course_id`` and ``report`` once it is done."""

    job_id: str
    status: JobStatus
    done: int
    total: int | None
    course_id: UUID | None
    error: str | None
    report: CartridgeImportReport | None


async def start_cartridge_import(
    file: Annotated[UploadFile, File()], actor: ActorDep, container: ContainerDep
) -> CartridgeImportStarted:
    """Upload an .imscc (at most 200 MB); the import runs in the background."""
    data = await file.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise CartridgeInvalidError(
            params={"reason": "too-large", "max_bytes": MAX_ARCHIVE_BYTES}
        )
    job_id = await container.lms.cartridge.start_import.execute(
        actor, name=file.filename or "course.imscc", data=data
    )
    return CartridgeImportStarted(job_id=job_id)


async def get_cartridge_import(
    job_id: str, actor: ActorDep, container: ContainerDep
) -> CartridgeImportStatus:
    """Poll an import started by the caller."""
    view = await container.lms.cartridge.get_import.execute(actor, job_id)
    return CartridgeImportStatus.model_validate(view)


async def export_cartridge(
    course_id: UUID, actor: ActorDep, container: ContainerDep
) -> Response:
    """Download the course draft as a Common Cartridge 1.3 (editors)."""
    exported = await container.lms.cartridge.export.execute(actor, course_id)
    return Response(
        content=exported.data,
        media_type="application/vnd.ims.imsccv1p3",
        headers={"Content-Disposition": f'attachment; filename="{exported.filename}"'},
    )


class CourseCopied(BaseModel):
    """The new draft course created by a copy."""

    course_id: UUID
    title: str


async def copy_course(
    course_id: UUID, actor: ActorDep, container: ContainerDep
) -> CourseCopied:
    """Copy the course draft as "<title> (copy)" owned by the caller (editors)."""
    copied = await container.lms.cartridge.copy.execute(actor, course_id)
    return CourseCopied(course_id=copied.course_id, title=copied.title)


router = APIRouter(prefix="/v1/lms", tags=["lms-authoring"])
router.add_api_route(
    "/courses/import", start_cartridge_import, methods=["POST"], status_code=202
)
router.add_api_route("/imports/{job_id}", get_cartridge_import, methods=["GET"])
router.add_api_route(
    "/courses/{course_id}/export.imscc",
    export_cartridge,
    methods=["GET"],
    response_class=Response,
    responses={200: {"content": {"application/vnd.ims.imsccv1p3": {}}}},
)
router.add_api_route(
    "/courses/{course_id}/copy", copy_course, methods=["POST"], status_code=201
)
