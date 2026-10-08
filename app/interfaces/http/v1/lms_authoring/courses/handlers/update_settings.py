"""PATCH /v1/lms/courses/{id}/settings: change visibility, status, cover."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    CourseDraftResponse,
    SettingsBody,
    respond,
)
from app.modules.lms.domain.authoring.unset import UNSET


async def update_settings(
    course_id: UUID, body: SettingsBody, actor: ActorDep, authoring: AuthoringDep
) -> CourseDraftResponse:
    """Apply the provided settings; `cover_file_id: null` removes the cover."""
    cover = body.cover_file_id if "cover_file_id" in body.model_fields_set else UNSET
    view = await authoring.update_course_settings.execute(
        actor,
        course_id,
        visibility=body.visibility,
        status=body.status,
        cover_file_id=cover,
    )
    return respond(CourseDraftResponse, view)
