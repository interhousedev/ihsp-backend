"""PATCH /v1/lms/courses/{id}/staff/{user_id}: change a staff member."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    CourseStaffItemResponse,
    UpdateStaffBody,
    respond,
)


async def update_staff(
    course_id: UUID,
    user_id: UUID,
    body: UpdateStaffBody,
    actor: ActorDep,
    authoring: AuthoringDep,
) -> CourseStaffItemResponse:
    """Apply a partial update to one staff member."""
    view = await authoring.update_course_staff.execute(
        actor,
        course_id,
        user_id,
        role=body.role,
        permissions=body.permissions,
        show_on_page=body.show_on_page,
        position=body.position,
    )
    return respond(CourseStaffItemResponse, view)
