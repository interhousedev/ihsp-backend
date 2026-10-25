"""GET /v1/lms/courses/{id}/staff: list course staff."""

from uuid import UUID

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    CourseStaffItemResponse,
    respond_list,
)


async def list_staff(
    course_id: UUID, actor: ActorDep, authoring: AuthoringDep
) -> list[CourseStaffItemResponse]:
    """Return every staff member of the course."""
    views = await authoring.list_course_staff.execute(actor, course_id)
    return respond_list(CourseStaffItemResponse, views)
