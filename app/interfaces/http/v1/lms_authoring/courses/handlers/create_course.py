"""POST /v1/lms/courses: create a course."""

from app.interfaces.http.v1.lms_authoring.dependencies import ActorDep, AuthoringDep
from app.interfaces.http.v1.lms_authoring.schemas import (
    CourseDraftResponse,
    CreateCourseBody,
    respond,
)


async def create_course(
    body: CreateCourseBody, actor: ActorDep, authoring: AuthoringDep
) -> CourseDraftResponse:
    """Create a course with an empty draft (LMS admins only)."""
    view = await authoring.create_course.execute(
        actor, title=body.title, slug=body.slug, visibility=body.visibility
    )
    return respond(CourseDraftResponse, view)
