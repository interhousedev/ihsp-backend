"""POST /v1/lms/courses/{id}/staff: add a staff member by login."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    AddStaffBody,
    CourseStaffItemResponse,
    respond,
)


async def add_staff(
    course_id: UUID, body: AddStaffBody, actor: ActorDep, authoring: AuthoringDep
) -> CourseStaffItemResponse:
    """Add the user with the given login; unknown login is `id/user-not-found`."""
    view = await authoring.add_course_staff.execute(
        actor,
        course_id,
        login=body.login,
        role=body.role,
        permissions=body.permissions,
        show_on_page=body.show_on_page,
        position=body.position,
    )
    return respond(CourseStaffItemResponse, view)
