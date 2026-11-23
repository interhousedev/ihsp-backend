"""HTML widget routes of the editor: upload a widget, launch a draft's widget."""

from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    HtmlWidgetLaunchResponse,
    HtmlWidgetPackageResponse,
    respond,
)
from app.modules.lms.domain.html_widget import WIDGET_MAX_UPLOAD_BYTES

from fastapi import File, Response, UploadFile


async def upload_html_widget(
    course_id: UUID,
    file: Annotated[UploadFile, File()],
    actor: ActorDep,
    authoring: AuthoringDep,
) -> HtmlWidgetPackageResponse:
    """Upload a widget: one `.html` file or a `.zip` with `index.html` at its root.

    Up to 20 MiB uploaded, 60 MiB unpacked and 500 files; needs `edit` on the course.
    """
    data = await file.read(WIDGET_MAX_UPLOAD_BYTES + 1)
    view = await authoring.upload_html_widget.execute(
        actor, course_id, data, file.filename or ""
    )
    return respond(HtmlWidgetPackageResponse, view)


async def preview_html_widget(
    course_id: UUID,
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: ActorDep,
    authoring: AuthoringDep,
) -> HtmlWidgetLaunchResponse:
    """Return the signed URL of a draft's HTML widget (`view_drafts`)."""
    response.headers["Cache-Control"] = "no-store"
    view = await authoring.preview_html_widget.execute(
        actor, course_id, step_id, block_id
    )
    return respond(HtmlWidgetLaunchResponse, view)
