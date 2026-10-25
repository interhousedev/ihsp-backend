"""H5P routes of the editor: upload a package, launch a draft's package."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    H5PLaunchResponse,
    H5PPackageResponse,
    respond,
)
from app.modules.lms.domain.h5p_package import H5P_MAX_PACKAGE_BYTES

from fastapi import File, Response, UploadFile


async def upload_h5p(
    course_id: UUID,
    file: Annotated[UploadFile, File()],
    actor: ActorDep,
    authoring: AuthoringDep,
) -> H5PPackageResponse:
    """Upload a `.h5p` package (zip, up to 100 MB); needs `edit` on the course."""
    data = await file.read(H5P_MAX_PACKAGE_BYTES + 1)
    view = await authoring.upload_h5p.execute(actor, course_id, data)
    return respond(H5PPackageResponse, view)


async def preview_h5p(
    course_id: UUID,
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: ActorDep,
    authoring: AuthoringDep,
) -> H5PLaunchResponse:
    """Return the signed base URL of a draft's H5P package (`view_drafts`)."""
    response.headers["Cache-Control"] = "no-store"
    view = await authoring.preview_h5p.execute(actor, course_id, step_id, block_id)
    return respond(H5PLaunchResponse, view)
