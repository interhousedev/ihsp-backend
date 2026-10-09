"""POST /v1/notebooks/course-workspaces."""

from app.interfaces.http.v1.notebooks.deps import MemberActor, WorkspaceNotebooks
from app.interfaces.http.v1.notebooks.schemas_workspace import (
    CourseWorkspaceResponse,
    OpenCourseWorkspaceBody,
)


async def open_course_workspace(
    body: OpenCourseWorkspaceBody, notebooks: WorkspaceNotebooks, actor: MemberActor
) -> CourseWorkspaceResponse:
    """Get or create the AI workspace of a course (creating it needs ``edit``)."""
    opened = await notebooks.open_course_workspace.execute(actor, body.course_id)
    return CourseWorkspaceResponse.from_view(opened, body.course_id)
