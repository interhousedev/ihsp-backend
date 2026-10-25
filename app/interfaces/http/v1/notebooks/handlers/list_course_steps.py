"""GET /v1/notebooks/{id}/course-steps."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import MemberActor, WorkspaceNotebooks
from app.interfaces.http.v1.notebooks.schemas_workspace import CourseStepsResponse


async def list_course_steps(
    notebook_id: UUID, notebooks: WorkspaceNotebooks, actor: MemberActor
) -> CourseStepsResponse:
    """Return the course's draft outline for the "add course steps" picker."""
    view = await notebooks.list_course_steps.execute(actor, notebook_id)
    return CourseStepsResponse.from_view(view)
