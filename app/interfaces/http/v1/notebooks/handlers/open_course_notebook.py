"""POST /v1/notebooks/course/{course_id}."""

from uuid import UUID

from app.interfaces.http.v1.notebooks.deps import OwnerActor, WorkspaceNotebooks
from app.interfaces.http.v1.notebooks.schemas_notebooks import NotebookItemResponse
from app.modules.notebooks.domain.errors import NotebookNotFoundError


async def open_course_notebook(
    course_id: UUID, notebooks: WorkspaceNotebooks, actor: OwnerActor
) -> NotebookItemResponse:
    """Get or create the caller's notebook of a course they are enrolled in.

    The course materials are its sources; a stranger or an unpublished course gets
    the 404 of a missing notebook.
    """
    notebook = await notebooks.provision_course_notebook.execute(
        actor.user_id, course_id, touch=True
    )
    if notebook is None:
        raise NotebookNotFoundError()
    return NotebookItemResponse.from_entity(notebook)
